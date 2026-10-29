"""Yozish (write) business logic — academics."""

from django.db import IntegrityError, transaction
from django.db.models import Max, Q

from apps.users.choices import UserRole, UserStatus
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
def create_course(*, name: str, description: str = "", status: str = CourseStatus.ACTIVE) -> Course:
    if status not in WRITABLE_COURSE_STATUSES:
        raise BusinessRuleError("Kurs faqat DRAFT yoki ACTIVE holatda yaratiladi.")
    return Course.objects.create(name=name, description=description, status=status)


def update_course(course: Course, **fields) -> Course:
    _ensure_course_editable(course)
    if "status" in fields and fields["status"] not in WRITABLE_COURSE_STATUSES:
        raise BusinessRuleError("Kurs holati faqat DRAFT yoki ACTIVE ga o‘zgartiriladi.")
    changed = [name for name in ("name", "description", "status") if name in fields]
    for name in changed:
        setattr(course, name, fields[name])
    if changed:
        course.save(update_fields=[*changed, "updated_at"])
    return course


def archive_course(course: Course) -> Course:
    if course.status != CourseStatus.ARCHIVED:
        course.status = CourseStatus.ARCHIVED
        course.save(update_fields=["status", "updated_at"])
    return course


def restore_course(course: Course) -> Course:
    if course.status == CourseStatus.ARCHIVED:
        course.status = CourseStatus.ACTIVE
        course.save(update_fields=["status", "updated_at"])
    return course


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
    if teacher.role != UserRole.TEACHER:
        raise BusinessRuleError("Faqat TEACHER rolidagi foydalanuvchini biriktirish mumkin.")
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
    for teacher in (main_teacher, support_teacher):
        if teacher is None:
            continue
        if teacher.role != UserRole.TEACHER or teacher.status != UserStatus.ACTIVE:
            raise BusinessRuleError("Guruhga faqat faol TEACHER biriktiriladi.")
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
) -> StudyGroup:
    _ensure_course_editable(course)
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
            )
    except IntegrityError as exc:
        raise ConflictError(GROUP_NAME_TAKEN) from exc


@transaction.atomic
def update_group(group: StudyGroup, **fields) -> StudyGroup:
    _ensure_group_editable(group)
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
            group.save(update_fields=[*changed, "updated_at"])
    except IntegrityError as exc:
        raise ConflictError(GROUP_NAME_TAKEN) from exc
    return group


def rename_group(group: StudyGroup, *, name: str) -> StudyGroup:
    return update_group(group, name=name)


def archive_group(group: StudyGroup) -> StudyGroup:
    _ensure_course_editable(group.course)
    if group.status != GroupStatus.ARCHIVED:
        group.status = GroupStatus.ARCHIVED
        group.save(update_fields=["status", "updated_at"])
    return group


def restore_group(group: StudyGroup) -> StudyGroup:
    _ensure_course_editable(group.course)
    if group.status == GroupStatus.ARCHIVED:
        group.status = GroupStatus.ACTIVE
        group.save(update_fields=["status", "updated_at"])
    return group


def delete_group(group: StudyGroup) -> None:
    """A’zoliklar CASCADE bilan o‘chadi; assignmentda ishlatilgan bo‘lsa `ProtectedError` -> 409."""
    _ensure_course_editable(group.course)
    group.delete()


def add_student_to_group(*, group: StudyGroup, student: User) -> GroupStudent:
    _ensure_group_editable(group)
    if student.role != UserRole.STUDENT:
        raise BusinessRuleError("Faqat STUDENT rolidagi foydalanuvchini guruhga qo‘shish mumkin.")
    is_enrolled = Enrollment.objects.filter(
        course_id=group.course_id, student=student, status=EnrollmentStatus.ACTIVE
    ).exists()
    if not is_enrolled:
        raise BusinessRuleError("Student avval kursga (ACTIVE holatda) yozilgan bo‘lishi kerak.")
    try:
        with transaction.atomic():
            return GroupStudent.objects.create(group=group, student=student)
    except IntegrityError as exc:
        raise ConflictError("Student bu guruhga allaqachon qo‘shilgan.") from exc


def remove_student_from_group(*, group_student: GroupStudent) -> None:
    _ensure_group_editable(group_student.group)
    group_student.delete()
