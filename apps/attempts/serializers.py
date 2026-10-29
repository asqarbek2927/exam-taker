from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.assignments.choices import ResultReviewMode
from apps.exams.serializers import CourseBriefSerializer
from apps.questions.serializers import QuestionDetailSerializer
from apps.users.serializers import UserBriefSerializer

from .choices import AttemptEventAction, AttemptEventType, AttemptStatus
from .models import (
    AttemptEvent,
    AttemptQuestion,
    AttemptQuestionOption,
    ExamAttempt,
    StudentAnswer,
)


class StudentSavedAnswerSerializer(serializers.Serializer):
    option_ids = serializers.ListField(child=serializers.UUIDField())
    text_answer = serializers.CharField(allow_blank=True)
    revision = serializers.IntegerField(min_value=0)


class StudentAttemptOptionSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="snapshot_option.source_option_id", read_only=True)
    text = serializers.CharField(source="snapshot_option.text", read_only=True)

    class Meta:
        model = AttemptQuestionOption
        fields = ["id", "text"]
        read_only_fields = fields


class StudentExamQuestionSerializer(serializers.ModelSerializer):
    """Persist qilingan attempt snapshot savoli; answer key chiqmaydi."""

    id = serializers.UUIDField(source="snapshot_question.source_exam_question_id", read_only=True)
    question_id = serializers.UUIDField(
        source="snapshot_question.source_question_id", read_only=True
    )
    text = serializers.CharField(source="snapshot_question.text", read_only=True)
    type = serializers.CharField(source="snapshot_question.type", read_only=True)
    points = serializers.DecimalField(
        source="snapshot_question.points", max_digits=6, decimal_places=2, read_only=True
    )
    options = StudentAttemptOptionSerializer(source="delivery_options", many=True, read_only=True)
    answer = serializers.SerializerMethodField()

    class Meta:
        model = AttemptQuestion
        fields = ["id", "question_id", "text", "type", "points", "position", "options", "answer"]
        read_only_fields = fields

    @extend_schema_field(StudentSavedAnswerSerializer(allow_null=True))
    def get_answer(self, obj: AttemptQuestion):
        answer: StudentAnswer | None = self.context.get("answers", {}).get(obj.id)
        if answer is None:
            return None
        return {
            "option_ids": [
                link.attempt_option.snapshot_option.source_option_id
                for link in answer.selected_options.all()
                if link.attempt_option_id is not None
            ],
            "text_answer": answer.text_answer,
            "revision": answer.revision,
        }


class _AttemptBaseSerializer(serializers.ModelSerializer):
    assignment_id = serializers.UUIDField(read_only=True)
    exam_id = serializers.UUIDField(source="assignment.exam_id", read_only=True)
    exam_title = serializers.SerializerMethodField()

    def get_exam_title(self, obj: ExamAttempt) -> str:
        snapshot = getattr(obj.assignment, "snapshot", None)
        return snapshot.title if snapshot is not None else obj.assignment.exam.title


class StudentAttemptSerializer(_AttemptBaseSerializer):
    duration_minutes = serializers.IntegerField(
        source="assignment.duration_minutes", read_only=True
    )
    server_now = serializers.SerializerMethodField()
    questions = serializers.SerializerMethodField()

    class Meta:
        model = ExamAttempt
        fields = [
            "id",
            "assignment_id",
            "exam_id",
            "exam_title",
            "attempt_number",
            "status",
            "started_at",
            "deadline_at",
            "duration_minutes",
            "focus_violations",
            "server_now",
            "questions",
        ]
        read_only_fields = fields

    def get_server_now(self, obj) -> str:
        return timezone.now().isoformat()

    @extend_schema_field(StudentExamQuestionSerializer(many=True))
    def get_questions(self, obj: ExamAttempt):
        attempt_questions = (
            obj.delivery_questions.select_related("snapshot_question")
            .prefetch_related("delivery_options__snapshot_option")
            .order_by("position")
        )
        answers = {
            answer.attempt_question_id: answer
            for answer in obj.answers.prefetch_related(
                "selected_options__attempt_option__snapshot_option"
            )
        }
        return StudentExamQuestionSerializer(
            attempt_questions, many=True, context={"answers": answers}
        ).data


class StudentResultAnswerSerializer(serializers.ModelSerializer):
    exam_question_id = serializers.SerializerMethodField()
    position = serializers.SerializerMethodField()
    max_points = serializers.SerializerMethodField()
    question = serializers.SerializerMethodField()
    selected_option_ids = serializers.SerializerMethodField()

    class Meta:
        model = StudentAnswer
        fields = [
            "exam_question_id",
            "position",
            "max_points",
            "question",
            "selected_option_ids",
            "text_answer",
            "is_correct",
            "points_awarded",
            "teacher_feedback",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.UUID)
    def get_exam_question_id(self, obj: StudentAnswer):
        if obj.attempt_question_id is not None:
            return obj.attempt_question.snapshot_question.source_exam_question_id
        return obj.exam_question_id

    def get_position(self, obj: StudentAnswer) -> int:
        if obj.attempt_question_id is not None:
            return obj.attempt_question.position
        return obj.exam_question.position

    @extend_schema_field(serializers.DecimalField(max_digits=6, decimal_places=2))
    def get_max_points(self, obj: StudentAnswer):
        if obj.attempt_question_id is not None:
            return obj.attempt_question.snapshot_question.points
        return obj.exam_question.points

    def get_question(self, obj: StudentAnswer) -> dict:
        include_correct = self.context.get("include_correct", False)
        if obj.attempt_question_id is not None:
            question = obj.attempt_question.snapshot_question
            options = []
            for option in question.options.all():
                item = {
                    "id": option.source_option_id,
                    "text": option.text,
                    "position": option.position,
                }
                if include_correct:
                    item["is_correct"] = option.is_correct
                options.append(item)
            return {
                "id": question.source_question_id,
                "type": question.type,
                "text": question.text,
                "options": options,
            }

        question = obj.exam_question.question
        options = []
        for option in question.options.all():
            item = {"id": option.id, "text": option.text, "position": option.position}
            if include_correct:
                item["is_correct"] = option.is_correct
            options.append(item)
        return {
            "id": question.id,
            "type": question.type,
            "text": question.text,
            "options": options,
        }

    def get_selected_option_ids(self, obj: StudentAnswer) -> list:
        return [
            link.attempt_option.snapshot_option.source_option_id
            if link.attempt_option_id is not None
            else link.option_id
            for link in obj.selected_options.all()
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.context.get("include_correct", False):
            data.pop("is_correct", None)
        return data


class AttemptResultSerializer(_AttemptBaseSerializer):
    review_mode = serializers.CharField(source="assignment.result_review_mode", read_only=True)
    answer_review_released = serializers.BooleanField(
        source="assignment.answer_review_released", read_only=True
    )
    answers = serializers.SerializerMethodField()

    class Meta:
        model = ExamAttempt
        fields = [
            "id",
            "assignment_id",
            "exam_id",
            "exam_title",
            "attempt_number",
            "status",
            "started_at",
            "submitted_at",
            "score",
            "percentage",
            "passed",
            "focus_violations",
            "finalization_reason",
            "review_mode",
            "answer_review_released",
            "answers",
        ]
        read_only_fields = fields

    def _answer_visibility(self, obj: ExamAttempt) -> tuple[bool, bool]:
        if obj.status != AttemptStatus.GRADED:
            return False, False
        mode = obj.assignment.result_review_mode
        if mode == ResultReviewMode.AFTER_GRADING:
            return True, False
        if mode == ResultReviewMode.FULL_REVIEW and obj.assignment.answer_review_released:
            return True, True
        return False, False

    @extend_schema_field(StudentResultAnswerSerializer(many=True))
    def get_answers(self, obj: ExamAttempt):
        visible, include_correct = self._answer_visibility(obj)
        if not visible:
            return []
        answers = getattr(obj, "_prefetched_objects_cache", {}).get("answers")
        if answers is None:
            answers = (
                obj.answers.select_related(
                    "exam_question__question",
                    "attempt_question__snapshot_question",
                )
                .prefetch_related(
                    "selected_options__attempt_option__snapshot_option",
                    "exam_question__question__options",
                    "attempt_question__snapshot_question__options",
                )
                .order_by("attempt_question__position", "exam_question__position")
            )
        return StudentResultAnswerSerializer(
            answers,
            many=True,
            context={"include_correct": include_correct},
        ).data

    def to_representation(self, instance):
        data = super().to_representation(instance)
        visible, _ = self._answer_visibility(instance)
        if not visible:
            data.pop("answers", None)
        return data


class AttemptListSerializer(_AttemptBaseSerializer):
    course = CourseBriefSerializer(source="assignment.exam.course", read_only=True)
    student = UserBriefSerializer(read_only=True)

    class Meta:
        model = ExamAttempt
        fields = [
            "id",
            "assignment_id",
            "exam_id",
            "exam_title",
            "course",
            "student",
            "attempt_number",
            "status",
            "started_at",
            "deadline_at",
            "submitted_at",
            "score",
            "percentage",
            "passed",
            "focus_violations",
            "finalization_reason",
        ]
        read_only_fields = fields


class StaffAnswerSerializer(serializers.ModelSerializer):
    exam_question_id = serializers.SerializerMethodField()
    position = serializers.SerializerMethodField()
    max_points = serializers.SerializerMethodField()
    question = serializers.SerializerMethodField()
    selected_option_ids = serializers.SerializerMethodField()
    graded_by = UserBriefSerializer(read_only=True)

    class Meta:
        model = StudentAnswer
        fields = [
            "id",
            "exam_question_id",
            "position",
            "max_points",
            "question",
            "selected_option_ids",
            "text_answer",
            "is_correct",
            "points_awarded",
            "teacher_feedback",
            "graded_by",
            "graded_at",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.UUID)
    def get_exam_question_id(self, obj: StudentAnswer):
        if obj.attempt_question_id is not None:
            return obj.attempt_question.snapshot_question.source_exam_question_id
        return obj.exam_question_id

    def get_position(self, obj: StudentAnswer) -> int:
        if obj.attempt_question_id is not None:
            return obj.attempt_question.position
        return obj.exam_question.position

    @extend_schema_field(serializers.DecimalField(max_digits=6, decimal_places=2))
    def get_max_points(self, obj: StudentAnswer):
        if obj.attempt_question_id is not None:
            return obj.attempt_question.snapshot_question.points
        return obj.exam_question.points

    def get_question(self, obj: StudentAnswer) -> dict:
        if obj.attempt_question_id is None:
            return QuestionDetailSerializer(obj.exam_question.question).data
        question = obj.attempt_question.snapshot_question
        return {
            "id": question.source_question_id,
            "module_id": question.source_module_id,
            "type": question.type,
            "difficulty": question.difficulty,
            "text": question.text,
            "default_points": question.points,
            "options": [
                {
                    "id": option.source_option_id,
                    "text": option.text,
                    "is_correct": option.is_correct,
                    "position": option.position,
                }
                for option in question.options.all()
            ],
        }

    def get_selected_option_ids(self, obj: StudentAnswer) -> list:
        return [
            link.attempt_option.snapshot_option.source_option_id
            if link.attempt_option_id is not None
            else link.option_id
            for link in obj.selected_options.all()
        ]


class AttemptEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttemptEvent
        fields = [
            "event_id",
            "type",
            "client_at",
            "received_at",
            "details",
            "counts_violation",
            "focus_violations",
            "action",
        ]
        read_only_fields = fields


class AttemptStaffDetailSerializer(AttemptListSerializer):
    answers = StaffAnswerSerializer(many=True, read_only=True)
    events = AttemptEventSerializer(many=True, read_only=True)

    class Meta(AttemptListSerializer.Meta):
        fields = [*AttemptListSerializer.Meta.fields, "answers", "events"]
        read_only_fields = fields


class AnswerInputSerializer(serializers.Serializer):
    option_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, max_length=50
    )
    text_answer = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=False, max_length=20000
    )
    revision = serializers.IntegerField(min_value=0)


class AttemptEventInputSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    type = serializers.ChoiceField(choices=AttemptEventType.choices)
    client_at = serializers.DateTimeField()
    details = serializers.DictField(required=False, default=dict)


class AttemptEventResponseSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    focus_violations = serializers.IntegerField(min_value=0)
    threshold = serializers.IntegerField(min_value=1)
    action = serializers.ChoiceField(choices=AttemptEventAction.choices)
    status = serializers.ChoiceField(choices=AttemptStatus.choices)
    submission_reason = serializers.CharField(allow_null=True)


class AnswerSerializer(serializers.ModelSerializer):
    exam_question_id = serializers.SerializerMethodField()
    option_ids = serializers.SerializerMethodField()

    class Meta:
        model = StudentAnswer
        fields = ["exam_question_id", "option_ids", "text_answer", "revision", "updated_at"]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.UUID)
    def get_exam_question_id(self, obj: StudentAnswer):
        if obj.attempt_question_id is not None:
            return obj.attempt_question.snapshot_question.source_exam_question_id
        return obj.exam_question_id

    def get_option_ids(self, obj: StudentAnswer) -> list:
        return [
            link.attempt_option.snapshot_option.source_option_id
            if link.attempt_option_id is not None
            else link.option_id
            for link in obj.selected_options.all()
        ]


class PendingAttemptSerializer(AttemptListSerializer):
    pending_answers_count = serializers.IntegerField(read_only=True)

    class Meta(AttemptListSerializer.Meta):
        fields = [*AttemptListSerializer.Meta.fields, "pending_answers_count"]
        read_only_fields = fields


class GradeInputSerializer(serializers.Serializer):
    points_awarded = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0)
    teacher_feedback = serializers.CharField(required=False, allow_blank=True, max_length=5000)


class AttemptSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExamAttempt
        fields = ["id", "status", "score", "percentage", "passed"]
        read_only_fields = fields


class GradeResponseSerializer(serializers.Serializer):
    answer = StaffAnswerSerializer()
    attempt = AttemptSummarySerializer()
