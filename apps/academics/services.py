"""Yozish (write) business logic — academics."""

from django.db import IntegrityError, transaction
from django.db.models import Max

from apps.users.choices import UserRole, UserStatus
from apps.users.models import User
from common.exceptions import BusinessRuleError, ConflictError

from .choices import CourseStatus, CourseTeacherType, EnrollmentStatus, ModuleStatus
from .models import Course, CourseTeacher, Enrollment, GroupStudent, Module, StudyGroup

ARCHIVED_COURSE = "Arxivlangan kursga o‘zgartirish kiritib bo‘lmaydi."


def _ensure_course_editable(course: Course) -> None:
    if course.status == CourseStatus.ARCHIVED:
        raise BusinessRuleError(ARCHIVED_COURSE)


# --------------------------------------------------------------------------
# Course
# --------------------------------------------------------------------------
def create_course(*, name: str, description: str = "") -> Course:
    return Course.objects.create(name=name, description=description)


def update_course(course: Course, **fields) -> Course:
    _ensure_course_editable(course)
    changed = [name for name in ("name", "description") if name in fields]
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


# --------------------------------------------------------------------------
# CourseTeacher
# --------------------------------------------------------------------------
def assign_teacher(*, course: Course, teacher: User, teacher_type: str) -> CourseTeacher:
    _ensure_course_editable(course)
    if teacher.role != UserRole.TEACHER:
        raise BusinessRuleError("Faqat TEACHER rolidagi foydalanuvchini biriktirish mumkin.")
    if teacher.status != UserStatus.ACTIVE:
        raise BusinessRuleError("Nofaol teacherni kursga biriktirib bo‘lmaydi.")
    try:
        with transaction.atomic():
            return CourseTeacher.objects.create(course=course, teacher=teacher, type=teacher_type)
    except IntegrityError as exc:
        raise ConflictError("Bu teacher kursga allaqachon biriktirilgan.") from exc


def change_teacher_type(*, course_teacher: CourseTeacher, teacher_type: str) -> CourseTeacher:
    _ensure_course_editable(course_teacher.course)
    if teacher_type not in CourseTeacherType.values:
        raise BusinessRuleError("Noto‘g‘ri teacher turi.")
    if course_teacher.type != teacher_type:
        course_teacher.type = teacher_type
        course_teacher.save(update_fields=["type"])
    return course_teacher


def remove_teacher(*, course_teacher: CourseTeacher) -> None:
    _ensure_course_editable(course_teacher.course)
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


def create_group(*, course: Course, name: str) -> StudyGroup:
    _ensure_course_editable(course)
    try:
        with transaction.atomic():
            return StudyGroup.objects.create(course=course, name=name)
    except IntegrityError as exc:
        raise ConflictError(GROUP_NAME_TAKEN) from exc


def rename_group(group: StudyGroup, *, name: str) -> StudyGroup:
    _ensure_course_editable(group.course)
    if group.name == name:
        return group
    group.name = name
    try:
        with transaction.atomic():
            group.save(update_fields=["name", "updated_at"])
    except IntegrityError as exc:
        raise ConflictError(GROUP_NAME_TAKEN) from exc
    return group


def delete_group(group: StudyGroup) -> None:
    """A’zoliklar CASCADE bilan o‘chadi; assignmentda ishlatilgan bo‘lsa `ProtectedError` -> 409."""
    _ensure_course_editable(group.course)
    group.delete()


def add_student_to_group(*, group: StudyGroup, student: User) -> GroupStudent:
    _ensure_course_editable(group.course)
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
    _ensure_course_editable(group_student.group.course)
    group_student.delete()
