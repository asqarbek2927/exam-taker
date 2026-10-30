"""Yozish (write) business logic — academics."""

from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.users.choices import EDUCATOR_ROLES, UserRole, UserStatus
from apps.users.models import User
from common.exceptions import BusinessRuleError, ConflictError

from .choices import CourseStatus, CourseTeacherType, EnrollmentStatus, GroupStatus, ModuleStatus
from .models import Course, CourseTeacher, Enrollment, GroupStudent, Module, StudyGroup

ARCHIVED_COURSE = "Arxivlangan kursga o‘zgartirish kiritib bo‘lmaydi."
MAIN_TEACHER_TAKEN = "Bu kursga MAIN teacher allaqachon biriktirilgan."
WRITABLE_COURSE_STATUSES = (CourseStatus.DRAFT, CourseStatus.ACTIVE)


def _ensure_course_editable(course: Course) -> None:
    if course.status == CourseStatus.ARCHIVED:
        raise BusinessRuleError(ARCHIVED_COURSE)


# --------------------------------------------------------------------------
# Course
# --------------------------------------------------------------------------
@transaction.atomic
def create_course(
    *,
    name: str,
    description: str = "",
    status: str = CourseStatus.ACTIVE,
    main_teacher: User | None = None,
    teachers: list[User] | None = None,
) -> Course:
    if status not in WRITABLE_COURSE_STATUSES:
        raise BusinessRuleError("Kurs faqat DRAFT yoki ACTIVE holatda yaratiladi.")
    course = Course.objects.create(name=name, description=description, status=status)
    _replace_course_teachers(
        course=course,
        main_teacher=main_teacher,
        teachers=teachers or ([] if main_teacher is None else [main_teacher]),
    )
    return course


@transaction.atomic
def update_course(course: Course, **fields) -> Course:
    course = Course.objects.select_for_update().get(pk=course.pk)
    _ensure_course_editable(course)
    if "status" in fields and fields["status"] not in WRITABLE_COURSE_STATUSES:
        raise BusinessRuleError("Kurs holati faqat DRAFT yoki ACTIVE ga o‘zgartiriladi.")
    expected_version = fields.pop("version", None)
    if expected_version is not None and expected_version != course.version:
        raise ConflictError(
            "Kurs versiyasi eskirgan. Maâ€™lumotni yangilab qayta urinib koâ€˜ring."
        )
    teachers_supplied = "teachers" in fields
    main_supplied = "main_teacher" in fields
    teachers = fields.pop("teachers", None)
    main_teacher = fields.pop("main_teacher", None)
    changed = [name for name in ("name", "description", "status") if name in fields]
    for name in changed:
        setattr(course, name, fields[name])
    if teachers_supplied or main_supplied:
        current = list(course.course_teachers.select_related("teacher"))
        if not teachers_supplied:
            teachers = [item.teacher for item in current]
        if not main_supplied:
            main_teacher = next(
                (item.teacher for item in current if item.type == CourseTeacherType.MAIN), None
            )
        _replace_course_teachers(course=course, main_teacher=main_teacher, teachers=teachers or [])
        changed.append("course_teachers")
    if changed:
        course.version += 1
        db_fields = [name for name in changed if name != "course_teachers"]
        course.save(update_fields=[*db_fields, "version", "updated_at"])
    return course


def _replace_course_teachers(
    *, course: Course, main_teacher: User | None, teachers: list[User]
) -> None:
    unique = {teacher.pk: teacher for teacher in teachers}
    if main_teacher is not None:
        unique[main_teacher.pk] = main_teacher
    for teacher in unique.values():
        if teacher.role not in EDUCATOR_ROLES or teacher.status != UserStatus.ACTIVE:
            raise BusinessRuleError("Kursga faqat faol educator biriktiriladi.")
    if main_teacher is not None and main_teacher.role != UserRole.TEACHER:
        raise BusinessRuleError("MAIN teacher faol TEACHER rolida boâ€˜lishi kerak.")

    removed_ids = set(course.course_teachers.values_list("teacher_id", flat=True)) - set(unique)
    if (
        removed_ids
        and StudyGroup.objects.filter(course=course)
        .filter(Q(main_teacher_id__in=removed_ids) | Q(support_teacher_id__in=removed_ids))
        .exists()
    ):
        raise ConflictError("Teacher avval kurs guruhlaridan olinishi kerak.")

    course.course_teachers.all().delete()
    CourseTeacher.objects.bulk_create(
        [
            CourseTeacher(
                course=course,
                teacher=teacher,
                type=(
                    CourseTeacherType.MAIN
                    if main_teacher is not None and teacher.pk == main_teacher.pk
                    else CourseTeacherType.SUPPORT
                ),
            )
            for teacher in unique.values()
        ]
    )


@transaction.atomic
def set_course_status(course: Course, *, status: str, version: int | None = None) -> Course:
    course = Course.objects.select_for_update().get(pk=course.pk)
    if version is not None and version != course.version:
        raise ConflictError(
            "Kurs versiyasi eskirgan. Maâ€™lumotni yangilab qayta urinib koâ€˜ring."
        )
    if status not in CourseStatus.values:
        raise BusinessRuleError("Notoâ€˜gâ€˜ri kurs holati.")
    allowed = {
        CourseStatus.DRAFT: {CourseStatus.ACTIVE, CourseStatus.ARCHIVED},
        CourseStatus.ACTIVE: {CourseStatus.DRAFT, CourseStatus.ARCHIVED},
        CourseStatus.ARCHIVED: {CourseStatus.ACTIVE},
    }
    if course.status != status and status not in allowed[course.status]:
        raise BusinessRuleError(f"{course.status} holatidan {status} holatiga oâ€˜tib boâ€˜lmaydi.")
    if course.status != status:
        course.status = status
        course.version += 1
        course.save(update_fields=["status", "version", "updated_at"])
    return course


def archive_course(course: Course) -> Course:
    return set_course_status(course, status=CourseStatus.ARCHIVED)


def restore_course(course: Course) -> Course:
    if course.status != CourseStatus.ARCHIVED:
        return course
    return set_course_status(course, status=CourseStatus.ACTIVE)


# --------------------------------------------------------------------------
# CourseTeacher
# --------------------------------------------------------------------------
def _ensure_main_teacher_available(*, course: Course, exclude_id=None) -> None:
    queryset = CourseTeacher.objects.filter(course=course, type=CourseTeacherType.MAIN)
    if exclude_id is not None:
        queryset = queryset.exclude(pk=exclude_id)
    if queryset.exists():
        raise ConflictError(MAIN_TEACHER_TAKEN)


def assign_teacher(*, course: Course, teacher: User, teacher_type: str) -> CourseTeacher:
    _ensure_course_editable(course)
    if teacher.role not in EDUCATOR_ROLES:
        raise BusinessRuleError("Faqat educator rolidagi foydalanuvchini biriktirish mumkin.")
    if teacher.role == UserRole.SUPPORT_TEACHER and teacher_type == CourseTeacherType.MAIN:
        raise BusinessRuleError("SUPPORT_TEACHER kursning MAIN teacheri bo‘la olmaydi.")
    if teacher.status != UserStatus.ACTIVE:
        raise BusinessRuleError("Nofaol teacherni kursga biriktirib bo‘lmaydi.")
    if teacher_type == CourseTeacherType.MAIN:
        _ensure_main_teacher_available(course=course)
    try:
        with transaction.atomic():
            return CourseTeacher.objects.create(course=course, teacher=teacher, type=teacher_type)
    except IntegrityError as exc:
        if teacher_type == CourseTeacherType.MAIN:
            raise ConflictError(MAIN_TEACHER_TAKEN) from exc
        raise ConflictError("Bu teacher kursga allaqachon biriktirilgan.") from exc


def change_teacher_type(*, course_teacher: CourseTeacher, teacher_type: str) -> CourseTeacher:
    _ensure_course_editable(course_teacher.course)
    if teacher_type not in CourseTeacherType.values:
        raise BusinessRuleError("Noto‘g‘ri teacher turi.")
    if course_teacher.type != teacher_type:
        if (
            course_teacher.teacher.role == UserRole.SUPPORT_TEACHER
            and teacher_type == CourseTeacherType.MAIN
        ):
            raise BusinessRuleError("SUPPORT_TEACHER kursning MAIN teacheri bo‘la olmaydi.")
        if teacher_type == CourseTeacherType.MAIN:
            _ensure_main_teacher_available(
                course=course_teacher.course, exclude_id=course_teacher.pk
            )
        course_teacher.type = teacher_type
        try:
            with transaction.atomic():
                course_teacher.save(update_fields=["type"])
        except IntegrityError as exc:
            if teacher_type == CourseTeacherType.MAIN:
                raise ConflictError(MAIN_TEACHER_TAKEN) from exc
            raise
    return course_teacher


def remove_teacher(*, course_teacher: CourseTeacher) -> None:
    _ensure_course_editable(course_teacher.course)
    if (
        StudyGroup.objects.filter(course=course_teacher.course)
        .filter(Q(main_teacher=course_teacher.teacher) | Q(support_teacher=course_teacher.teacher))
        .exists()
    ):
        raise ConflictError("Teacher avval kurs guruhlaridan olinishi kerak.")
    course_teacher.delete()


# --------------------------------------------------------------------------
# Enrollment
# --------------------------------------------------------------------------
@transaction.atomic
def enroll_student(*, course: Course, student: User) -> Enrollment:
    _ensure_course_editable(course)
    if student.role != UserRole.STUDENT:
        raise BusinessRuleError("Faqat STUDENT rolidagi foydalanuvchini yozish mumkin.")
    if student.status != UserStatus.ACTIVE:
        raise BusinessRuleError("Nofaol studentni kursga yozib bo‘lmaydi.")

    existing = Enrollment.objects.select_for_update().filter(course=course, student=student).first()
    if existing is not None:
        if existing.status == EnrollmentStatus.ACTIVE:
            raise ConflictError("Student bu kursga allaqachon yozilgan.")
        # REMOVED / COMPLETED -> qayta faollashtiriladi (TZ 7.3).
        existing.status = EnrollmentStatus.ACTIVE
        existing.save(update_fields=["status"])
        return existing

    try:
        with transaction.atomic():
            return Enrollment.objects.create(course=course, student=student)
    except IntegrityError as exc:  # parallel so‘rov
        raise ConflictError("Student bu kursga allaqachon yozilgan.") from exc


@transaction.atomic
def change_enrollment_status(*, enrollment: Enrollment, status: str) -> Enrollment:
    _ensure_course_editable(enrollment.course)
    if status not in EnrollmentStatus.values:
        raise BusinessRuleError("Noto‘g‘ri enrollment holati.")
    if enrollment.status != status:
        enrollment.status = status
        enrollment.save(update_fields=["status"])
        if status == EnrollmentStatus.REMOVED:
            _drop_group_memberships(enrollment)
    return enrollment


def _drop_group_memberships(enrollment: Enrollment) -> None:
    """Kursdan chiqarilgan student shu kursdagi guruhlardan ham chiqariladi."""
    GroupStudent.objects.filter(
        group__course_id=enrollment.course_id, student_id=enrollment.student_id
    ).delete()


@transaction.atomic
def remove_enrollment(*, enrollment: Enrollment) -> None:
    """Student o‘chirilmaydi — `REMOVED` holatiga o‘tadi (idempotent)."""
    _ensure_course_editable(enrollment.course)
    if enrollment.status != EnrollmentStatus.REMOVED:
        enrollment.status = EnrollmentStatus.REMOVED
        enrollment.save(update_fields=["status"])
    _drop_group_memberships(enrollment)


# --------------------------------------------------------------------------
# Module
# --------------------------------------------------------------------------
def create_module(
    *, course: Course, title: str, description: str = "", position: int | None = None
) -> Module:
    _ensure_course_editable(course)
    if position is None:
        last = Module.objects.filter(course=course).aggregate(last=Max("position"))["last"]
        position = (last or 0) + 1
    return Module.objects.create(
        course=course, title=title, description=description, position=position
    )


def set_module_status(module: Module, *, status: str) -> Module:
    _ensure_course_editable(module.course)
    if status not in ModuleStatus.values:
        raise BusinessRuleError("Notoâ€˜gâ€˜ri modul holati.")
    if module.status != status:
        module.status = status
        module.save(update_fields=["status", "updated_at"])
    return module


@transaction.atomic
def reorder_modules(*, course: Course, module_ids: list) -> list[Module]:
    _ensure_course_editable(course)
    modules = list(Module.objects.select_for_update().filter(course=course))
    current_ids = {module.pk for module in modules}
    supplied_ids = set(module_ids)
    if len(module_ids) != len(supplied_ids) or supplied_ids != current_ids:
        raise BusinessRuleError(
            "moduleIds kurs modullarining takrorlanmagan aniq toâ€˜plami boâ€˜lishi kerak."
        )
    by_id = {module.pk: module for module in modules}
    ordered = []
    updated_at = timezone.now()
    for position, module_id in enumerate(module_ids, start=1):
        module = by_id[module_id]
        module.position = position
        module.updated_at = updated_at
        ordered.append(module)
    Module.objects.bulk_update(ordered, ["position", "updated_at"])
    return ordered


def update_module(module: Module, **fields) -> Module:
    _ensure_course_editable(module.course)
    changed = [name for name in ("title", "description", "position") if name in fields]
    for name in changed:
        setattr(module, name, fields[name])
    if changed:
        module.save(update_fields=[*changed, "updated_at"])
    return module


def delete_or_archive_module(module: Module) -> bool:
    """Bo‘sh va ishlatilmagan modul — o‘chiriladi; aks holda `ARCHIVED` (TZ 7.6).

    Qaytaradi: `True` — arxivlandi, `False` — o‘chirildi.
    """
    _ensure_course_editable(module.course)
    in_use = module.questions.exists() or module.exam_modules.exists()
    if in_use:
        if module.status != ModuleStatus.ARCHIVED:
            module.status = ModuleStatus.ARCHIVED
            module.save(update_fields=["status", "updated_at"])
        return True
    module.delete()
    return False


# --------------------------------------------------------------------------
# StudyGroup
# --------------------------------------------------------------------------
GROUP_NAME_TAKEN = "Bu kursda bunday nomli guruh allaqachon mavjud."


def _validate_group_teachers(
    *, course: Course, main_teacher: User | None, support_teacher: User | None
) -> None:
    if main_teacher is not None and main_teacher == support_teacher:
        raise BusinessRuleError("MAIN va SUPPORT teacher bir xil bo‘lishi mumkin emas.")
    if main_teacher is not None and (
        main_teacher.role != UserRole.TEACHER or main_teacher.status != UserStatus.ACTIVE
    ):
        raise BusinessRuleError("Guruhning MAIN teacheri faol TEACHER bo‘lishi kerak.")
    if support_teacher is not None and (
        support_teacher.role not in EDUCATOR_ROLES or support_teacher.status != UserStatus.ACTIVE
    ):
        raise BusinessRuleError("Guruhning SUPPORT teacheri faol educator bo‘lishi kerak.")
    for teacher in (main_teacher, support_teacher):
        if teacher is None:
            continue
        if not CourseTeacher.objects.filter(course=course, teacher=teacher).exists():
            raise BusinessRuleError("Teacher avval guruh kursiga biriktirilgan bo‘lishi kerak.")


def _ensure_group_editable(group: StudyGroup) -> None:
    _ensure_course_editable(group.course)
    if group.status == GroupStatus.ARCHIVED:
        raise BusinessRuleError("Arxivlangan guruhga o‘zgartirish kiritib bo‘lmaydi.")


@transaction.atomic
def create_group(
    *,
    course: Course,
    name: str,
    main_teacher: User | None = None,
    support_teacher: User | None = None,
    status: str = GroupStatus.ACTIVE,
) -> StudyGroup:
    _ensure_course_editable(course)
    if status not in GroupStatus.values:
        raise BusinessRuleError("Noto‘g‘ri guruh holati.")
    _validate_group_teachers(
        course=course, main_teacher=main_teacher, support_teacher=support_teacher
    )
    try:
        with transaction.atomic():
            return StudyGroup.objects.create(
                course=course,
                name=name,
                main_teacher=main_teacher,
                support_teacher=support_teacher,
                status=status,
            )
    except IntegrityError as exc:
        raise ConflictError(GROUP_NAME_TAKEN) from exc


@transaction.atomic
def update_group(group: StudyGroup, **fields) -> StudyGroup:
    group = StudyGroup.objects.select_for_update().get(pk=group.pk)
    _ensure_group_editable(group)
    expected_version = fields.pop("version", None)
    if expected_version is not None and expected_version != group.version:
        raise ConflictError("Guruh versiyasi eskirgan. Ma’lumotni yangilab qayta urinib ko‘ring.")
    changed = [name for name in ("name", "main_teacher", "support_teacher") if name in fields]
    if not changed:
        return group
    main_teacher = fields.get("main_teacher", group.main_teacher)
    support_teacher = fields.get("support_teacher", group.support_teacher)
    _validate_group_teachers(
        course=group.course,
        main_teacher=main_teacher,
        support_teacher=support_teacher,
    )
    for name in changed:
        setattr(group, name, fields[name])
    try:
        with transaction.atomic():
            group.version += 1
            group.save(update_fields=[*changed, "version", "updated_at"])
    except IntegrityError as exc:
        raise ConflictError(GROUP_NAME_TAKEN) from exc
    return group


def rename_group(group: StudyGroup, *, name: str) -> StudyGroup:
    return update_group(group, name=name)


@transaction.atomic
def set_group_status(group: StudyGroup, *, status: str, version: int | None = None) -> StudyGroup:
    group = StudyGroup.objects.select_for_update().get(pk=group.pk)
    _ensure_course_editable(group.course)
    if version is not None and version != group.version:
        raise ConflictError("Guruh versiyasi eskirgan. Ma’lumotni yangilab qayta urinib ko‘ring.")
    if status not in GroupStatus.values:
        raise BusinessRuleError("Noto‘g‘ri guruh holati.")
    if status == GroupStatus.ACTIVE and group.status != GroupStatus.ACTIVE:
        student_ids = group.group_students.values("student_id")
        conflict = GroupStudent.objects.filter(
            student_id__in=student_ids,
            group__course=group.course,
            group__status=GroupStatus.ACTIVE,
        ).exclude(group=group)
        if conflict.exists():
            raise ConflictError(
                "Guruhni faollashtirib bo‘lmaydi: ayrim studentlar kursning boshqa faol guruhida."
            )
    if group.status != status:
        group.status = status
        group.version += 1
        group.save(update_fields=["status", "version", "updated_at"])
    return group


def archive_group(group: StudyGroup) -> StudyGroup:
    return set_group_status(group, status=GroupStatus.ARCHIVED)


def restore_group(group: StudyGroup) -> StudyGroup:
    if group.status != GroupStatus.ARCHIVED:
        return group
    return set_group_status(group, status=GroupStatus.ACTIVE)


def delete_group(group: StudyGroup) -> None:
    """A’zoliklar CASCADE bilan o‘chadi; assignmentda ishlatilgan bo‘lsa `ProtectedError` -> 409."""
    _ensure_course_editable(group.course)
    group.delete()


@transaction.atomic
def add_student_to_group(*, group: StudyGroup, student: User) -> GroupStudent:
    group = StudyGroup.objects.select_for_update().select_related("course").get(pk=group.pk)
    _ensure_group_editable(group)
    if student.role != UserRole.STUDENT:
        raise BusinessRuleError("Faqat STUDENT rolidagi foydalanuvchini guruhga qo‘shish mumkin.")
    if student.status != UserStatus.ACTIVE:
        raise BusinessRuleError("Faqat faol studentni guruhga qo‘shish mumkin.")
    if group.course.status != CourseStatus.ACTIVE:
        raise BusinessRuleError("Student faqat ACTIVE kursdagi guruhga qo‘shiladi.")
    enrollment = (
        Enrollment.objects.select_for_update()
        .filter(course_id=group.course_id, student=student, status=EnrollmentStatus.ACTIVE)
        .first()
    )
    if enrollment is None:
        raise BusinessRuleError("Student avval kursga (ACTIVE holatda) yozilgan bo‘lishi kerak.")
    if (
        GroupStudent.objects.filter(
            student=student,
            group__course=group.course,
            group__status=GroupStatus.ACTIVE,
        )
        .exclude(group=group)
        .exists()
    ):
        raise ConflictError("Student bu kursning boshqa faol guruhiga allaqachon biriktirilgan.")
    try:
        with transaction.atomic():
            return GroupStudent.objects.create(group=group, student=student)
    except IntegrityError as exc:
        raise ConflictError("Student bu guruhga allaqachon qo‘shilgan.") from exc


def remove_student_from_group(*, group_student: GroupStudent) -> None:
    # Archived groupdan membershipni tozalash restore conflictini yechish uchun ruxsat etiladi.
    _ensure_course_editable(group_student.group.course)
    group_student.delete()
