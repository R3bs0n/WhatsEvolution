from django import forms

from .models import Atendimento, SituacaoAtendimento


class AtendimentoForm(forms.ModelForm):
    class Meta:
        model = Atendimento
        fields = [
            "situacao",
            "paciente",
            "telefone",
            "exame_procedimento",
            "idade",
            "data_agendamento",
            "horario_agendamento",
            "profissional_executante",
            "un_executante",
            "un_solicitante",
            "observacao",
        ]
        widgets = {
            "data_agendamento": forms.DateInput(attrs={"type": "date"}),
            "horario_agendamento": forms.TimeInput(attrs={"type": "time"}),
            "observacao": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["situacao"].queryset = SituacaoAtendimento.objects.filter(ativo=True)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
