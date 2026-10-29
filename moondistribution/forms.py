"""Forms for rounds, moons, settings and applications."""

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import DistributionSettings, Moon, Round, RoundBonus


def distributable_moons():
    """Active moons that may go into a round (R64 excluded if the setting says so)."""
    qs = Moon.objects.filter(is_active=True)
    if DistributionSettings.get_solo().exclude_r64:
        qs = qs.exclude(rarity=Moon.Rarity.R64)
    return qs


class DateInput(forms.DateInput):
    """HTML5 date picker."""

    input_type = "date"

    def __init__(self, **kwargs):
        kwargs.setdefault("format", "%Y-%m-%d")
        super().__init__(**kwargs)


class RoundForm(forms.ModelForm):
    """Create/edit a round including its moon pool."""

    moons = forms.ModelMultipleChoiceField(
        queryset=Moon.objects.filter(is_active=True),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text=_("Moons that are up for distribution in this round."),
    )

    class Meta:
        model = Round
        fields = ["name", "description", "evaluation_start", "evaluation_end", "moons"]
        widgets = {
            "evaluation_start": DateInput(),
            "evaluation_end": DateInput(),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        """Pre-select all distributable moons for a new round (no R64 if excluded)."""
        super().__init__(*args, **kwargs)
        self.fields["moons"].queryset = distributable_moons()
        if not self.instance.pk:
            self.initial.setdefault("moons", list(distributable_moons().values_list("pk", flat=True)))
        for name, field in self.fields.items():
            if name != "moons":
                field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        """Check that the activity window makes sense."""
        data = super().clean()
        ev_start, ev_end = data.get("evaluation_start"), data.get("evaluation_end")
        if ev_start and ev_end and ev_end <= ev_start:
            self.add_error("evaluation_end", _("Must be after the evaluation start."))
        return data


class MoonForm(forms.ModelForm):
    """Add/edit a moon manually (e.g. rarity, notes)."""

    class Meta:
        model = Moon
        fields = ["name", "system_name", "region_name", "rarity", "notes", "is_active"]

    def __init__(self, *args, **kwargs):
        """Bootstrap classes for all inputs."""
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            css = "form-check-input" if name == "is_active" else ("form-select" if name == "rarity" else "form-control")
            field.widget.attrs.setdefault("class", css)


class SettingsForm(forms.ModelForm):
    """Settings page for the Mining Officer."""

    class Meta:
        model = DistributionSettings
        fields = ["alliance_id", "weight_mining", "weight_pvp", "weight_members", "weight_fleet",
                  "per_member", "application_days", "max_moons_per_corp", "max_wishes", "active_days",
                  "allow_directors", "exclude_r64", "max_r32_per_corp", "max_r16_per_corp",
                  "bonus_no_moon", "bonus_no_r32"]

    def __init__(self, *args, **kwargs):
        """Bootstrap classes for all inputs."""
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            is_bool = isinstance(field, forms.BooleanField)
            field.widget.attrs.setdefault("class", "form-check-input" if is_bool else "form-control")

    def clean(self):
        """At least one criterion must have a weight > 0."""
        data = super().clean()
        weights = [data.get(f) for f in ("weight_mining", "weight_pvp", "weight_members", "weight_fleet")]
        if all(w is not None for w in weights) and sum(weights) == 0:
            raise forms.ValidationError(_("At least one weight must be greater than 0."))
        return data


class RoundBonusForm(forms.ModelForm):
    """Manual bonus/malus points for one corp in a round."""

    class Meta:
        model = RoundBonus
        fields = ["corporation", "points", "reason"]

    def __init__(self, *args, corporations=None, **kwargs):
        """Limit the corp choice to the given queryset (alliance corps)."""
        super().__init__(*args, **kwargs)
        if corporations is not None:
            self.fields["corporation"].queryset = corporations
        self.fields["corporation"].widget.attrs["class"] = "form-select form-select-sm"
        self.fields["points"].widget.attrs.update({"class": "form-control form-control-sm", "min": -100, "max": 100})
        self.fields["reason"].widget.attrs.update({"class": "form-control form-control-sm"})


def parse_wishlist(post_data, moons, max_wishes: int):
    """Read the priority inputs (name 'prio_<moon_id>') of the apply form.

    Returns (list of (priority, moon), list of error strings). Empty inputs = not wanted.
    """
    wishes, errors = [], []
    for moon in moons:
        raw = (post_data.get(f"prio_{moon.pk}") or "").strip()
        if raw == "":
            continue
        try:
            prio = int(raw)
        except ValueError:
            errors.append(_("Priority for %(moon)s is not a number.") % {"moon": moon.name})
            continue
        if prio < 1:
            errors.append(_("Priority for %(moon)s must be 1 or higher.") % {"moon": moon.name})
            continue
        wishes.append((prio, moon))

    prios = [p for p, _m in wishes]
    if len(prios) != len(set(prios)):
        errors.append(_("Every priority may only be used once."))
    if len(wishes) > max_wishes:
        errors.append(_("You can choose at most %(n)s moons.") % {"n": max_wishes})
    if not wishes and not errors:
        errors.append(_("Choose at least one moon."))

    # Renumber to 1..n so gaps (1, 3, 7) don't matter
    wishes.sort(key=lambda w: w[0])
    return [(i, moon) for i, (_p, moon) in enumerate(wishes, start=1)], errors
