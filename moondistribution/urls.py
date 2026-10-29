"""URL routes of Moon Distribution."""

from django.urls import path

from . import views

app_name = "moondistribution"

urlpatterns = [
    # Overview with open rounds and history
    path("", views.index, name="index"),
    # "How it works" guide for the corps (all AA languages)
    path("guide/", views.guide, name="guide"),
    # Round details, results and applications
    path("round/<int:round_id>/", views.round_detail, name="round_detail"),
    # Apply / change wishlist for a corp
    path("round/<int:round_id>/apply/<int:corporation_id>/", views.apply, name="apply"),
    # Withdraw an application
    path("round/<int:round_id>/withdraw/<int:corporation_id>/", views.withdraw, name="withdraw"),
    # Officer: manual bonus points per corp
    path("round/<int:round_id>/bonus/", views.bonus_save, name="bonus_save"),
    path("round/<int:round_id>/bonus/<int:bonus_id>/delete/", views.bonus_delete, name="bonus_delete"),
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
    # Officer: bulk edit and rarity import (moon scans / aa-moonmining)
    path("moons/bulk/", views.moon_bulk, name="moon_bulk"),
    path("moons/rarity-import/", views.moon_rarity_import, name="moon_rarity_import"),
    # Officer: settings
    path("settings/", views.settings_view, name="settings"),
    # officer: alliance corps, probation and exceptions
    path("corps/", views.corps, name="corps"),
    path("corps/refresh/", views.corps_refresh, name="corps_refresh"),
    path("corps/<int:corporation_id>/exempt/", views.corp_exempt, name="corp_exempt"),
]
