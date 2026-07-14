from rest_framework import serializers, viewsets

from .models import EnvioWhatsAppLog


class EnvioWhatsAppLogSerializer(serializers.ModelSerializer):
    paciente = serializers.CharField(source="atendimento.paciente", read_only=True)

    class Meta:
        model = EnvioWhatsAppLog
        fields = [
            "id", "atendimento", "paciente", "telefone", "mensagem",
            "sucesso", "status_retorno", "codigo_retorno", "enviado_em",
        ]
        read_only_fields = fields


class EnvioWhatsAppLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EnvioWhatsAppLogSerializer

    def get_queryset(self):
        empresa = getattr(self.request, "empresa", None)
        qs = (
            EnvioWhatsAppLog.objects.for_empresa(empresa)
            .select_related("atendimento")
            .order_by("-enviado_em")
        )
        sucesso = self.request.query_params.get("sucesso")
        if sucesso is not None:
            qs = qs.filter(sucesso=sucesso.lower() == "true")
        return qs
