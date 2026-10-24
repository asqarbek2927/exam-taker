from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import BaseUserCreationForm, UserChangeForm

from .models import User


class HttpsURLField(forms.URLField):
    """Django 6.0 da default sxema `https` bo‘ladi — hozirdanoq shunday."""

    def __init__(self, **kwargs):
        kwargs.setdefault("assume_scheme", "https")
        super().__init__(**kwargs)


class UserAdminCreationForm(BaseUserCreationForm):
    class Meta:
        model = User
        fields = ("email", "full_name", "role")


class UserAdminChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"
        field_classes = {"avatar_url": HttpsURLField}


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm
    list_display = ("email", "full_name", "role", "status", "created_at")
    list_filter = ("role", "status")
    search_fields = ("email", "full_name")
    ordering = ("email",)
    readonly_fields = ("id", "last_login", "created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("id", "email", "password")}),
        ("Profil", {"fields": ("full_name", "avatar_url")}),
        ("Rol va holat", {"fields": ("role", "status")}),
        ("Sanalar", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "role", "password1", "password2"),
            },
        ),
    )
    filter_horizontal = ()
