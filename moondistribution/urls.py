"""URL routes of Moon Distribution."""

from django.urls import path

from . import views

app_name = "moondistribution"

urlpatterns = [
    # Overview with open rounds and history
    path("", views.index, name="index"),
    # Round details, results and applications
    path("round/<int:round_id>/", views.round_detail, name="round_detail"),
    # Apply / change wishlist for a corp
    path("round/<int:round_id>/apply/<int:corporation_id>/", views.apply, name="apply"),
    # Withdraw an application
    path("round/<int:round_id>/withdraw/<int:corporation_id>/", views.withdraw, name="withdraw"),
    # Officer: apply on behalf of any alliance corp
    path("round/<int:round_id>/apply-for/", views.officer_apply, name="officer_apply"),
    # Officer: round management
    path("round/new/", views.round_create, name="round_create"),
    path("round/<int:round_id>/edit/", views.round_edit, name="round_edit"),
    path("round/<int:round_id>/open/", views.round_open, name="round_open"),
    path("round/<int:round_id>/close-now/", views.round_close_now, name="round_close_now"),
    path("round/<int:round_id>/redistribute/", views.round_redistribute, name="round_redistribute"),
    path("round/<int:round_id>/delete/", views.round_delete, name="round_delete"),
    # Officer: moons
    path("moons/", views.moons, name="moons"),
    path("moons/new/", views.moon_edit, name="moon_add"),
    path("moons/<int:moon_id>/edit/", views.moon_edit, name="moon_edit"),
    path("moons/sync/", views.moon_sync, name="moon_sync"),
    # Officer: settings
    path("settings/", views.settings_view, name="settings"),
]
