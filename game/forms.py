from django import forms
from django.core.exceptions import ValidationError

from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance
from game.models import TeamTowerChallenge, Tower
from organize.models import Team


class RFIDTowerForm(forms.Form):
    class Meta:
        model = TeamTowerChallenge
        fields = ["rfid_code", "team_code", "lng", "lat"]

    lng = forms.FloatField(required=True)
    lat = forms.FloatField(required=True)
    team_code = forms.CharField(required=True)
    rfid_code = forms.CharField(required=True)

    def clean_rfid_code(self):
        try:
            t = Tower.objects.get(rfid_code=self.cleaned_data['rfid_code'], is_active=True, category=Tower.CATEGORY_RFID)
        except Tower.DoesNotExist:
            raise ValidationError("Turn cu acest RFID code nu exista")
        return t

    def clean_team_code(self):
        try:
            t = Team.objects.get(code=self.cleaned_data['team_code'])
        except Team.DoesNotExist:
            raise ValidationError("Cod de echipa incorect")
        return t

    def clean(self):
        point = Point(self.cleaned_data['lng'], self.cleaned_data['lat'])
        radius = 50
        try:
            Tower.objects.get(pk=self.cleaned_data['rfid_code'].id, is_active=True, category=Tower.CATEGORY_RFID,
                              location__distance_lt=(point, Distance(m=radius)))
        except Tower.DoesNotExist:
            raise ValidationError("Nu te gasesti in apropierea turnului! {} {}".format(self.cleaned_data['lng'], self.cleaned_data['lat']))

        return self.cleaned_data
