from rest_framework import serializers, viewsets

from .models import Atendimento


class AtendimentoSerializer(serializers.ModelSerializer):
    situacao_nome = serializers.CharField(source="situacao.nome", read_only=True)

    class Meta:
        model = Atendimento
        fields = [
            "id", "paciente", "telefone", "exame_procedimento",
            "data_agendamento", "horario_agendamento", "status_enviado",
            "data_envio", "situacao", "situacao_nome", "criado_em",
        ]
        read_only_fields = ["criado_em", "data_envio"]


class AtendimentoViewSet(viewsets.ModelViewSet):
    serializer_class = AtendimentoSerializer
    queryset = Atendimento.objects.select_related("situacao").order_by("-criado_em")

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.query_params.get("q", "")
        if q:
            qs = qs.filter(paciente__icontains=q) | qs.filter(telefone__icontains=q)
        status = self.request.query_params.get("status", "")
        if status in ("N", "S"):
            qs = qs.filter(status_enviado=status)
        return qs
