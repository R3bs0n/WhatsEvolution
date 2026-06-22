-- Habilita RLS em todas as tabelas operacionais.
-- Executar como migrate_role (BYPASSRLS) ou superuser.
-- NÃO aplicar em: empresas_empresa, empresas_membroempresa, billing_plano, billing_assinatura.
-- Depois de rodar este script, reiniciar webhook e celery para que as queries incluam
-- SET LOCAL app.current_tenant = <empresa_id> antes de cada operação.

-- Helper function para extrair tenant do contexto da sessão
CREATE OR REPLACE FUNCTION current_empresa_id() RETURNS bigint AS $$
  SELECT NULLIF(current_setting('app.current_tenant', true), '')::bigint;
$$ LANGUAGE sql STABLE;


-- ── TABELAS OPERACIONAIS ──────────────────────────────────────────────────────

-- atendimentos
ALTER TABLE atendimentos ENABLE ROW LEVEL SECURITY;
ALTER TABLE atendimentos FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON atendimentos;
CREATE POLICY tenant_isolation ON atendimentos
    USING (empresa_id = current_empresa_id())
    WITH CHECK (empresa_id = current_empresa_id());

-- situacoes_atendimento
ALTER TABLE situacoes_atendimento ENABLE ROW LEVEL SECURITY;
ALTER TABLE situacoes_atendimento FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON situacoes_atendimento;
CREATE POLICY tenant_isolation ON situacoes_atendimento
    USING (empresa_id = current_empresa_id())
    WITH CHECK (empresa_id = current_empresa_id());

-- status_atendimento
ALTER TABLE status_atendimento ENABLE ROW LEVEL SECURITY;
ALTER TABLE status_atendimento FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON status_atendimento;
CREATE POLICY tenant_isolation ON status_atendimento
    USING (empresa_id = current_empresa_id())
    WITH CHECK (empresa_id = current_empresa_id());

-- pdf_import_pdfimportlog
ALTER TABLE pdf_import_pdfimportlog ENABLE ROW LEVEL SECURITY;
ALTER TABLE pdf_import_pdfimportlog FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON pdf_import_pdfimportlog;
CREATE POLICY tenant_isolation ON pdf_import_pdfimportlog
    USING (empresa_id = current_empresa_id())
    WITH CHECK (empresa_id = current_empresa_id());

-- contatos_bloqueados
ALTER TABLE contatos_bloqueados ENABLE ROW LEVEL SECURITY;
ALTER TABLE contatos_bloqueados FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON contatos_bloqueados;
CREATE POLICY tenant_isolation ON contatos_bloqueados
    USING (empresa_id = current_empresa_id())
    WITH CHECK (empresa_id = current_empresa_id());

-- whatsapp_canalwhatsapp
ALTER TABLE whatsapp_canalwhatsapp ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_canalwhatsapp FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON whatsapp_canalwhatsapp;
CREATE POLICY tenant_isolation ON whatsapp_canalwhatsapp
    USING (empresa_id = current_empresa_id())
    WITH CHECK (empresa_id = current_empresa_id());

-- whatsapp_configuracaodisparo
ALTER TABLE whatsapp_configuracaodisparo ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_configuracaodisparo FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON whatsapp_configuracaodisparo;
CREATE POLICY tenant_isolation ON whatsapp_configuracaodisparo
    USING (empresa_id = current_empresa_id())
    WITH CHECK (empresa_id = current_empresa_id());

-- whatsapp_templatemensagem
ALTER TABLE whatsapp_templatemensagem ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_templatemensagem FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON whatsapp_templatemensagem;
CREATE POLICY tenant_isolation ON whatsapp_templatemensagem
    USING (empresa_id = current_empresa_id())
    WITH CHECK (empresa_id = current_empresa_id());

-- whatsapp_enviomensagem
ALTER TABLE whatsapp_enviomensagem ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_enviomensagem FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON whatsapp_enviomensagem;
CREATE POLICY tenant_isolation ON whatsapp_enviomensagem
    USING (empresa_id = current_empresa_id())
    WITH CHECK (empresa_id = current_empresa_id());

-- whatsapp_enviowhatsapplog
ALTER TABLE whatsapp_enviowhatsapplog ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_enviowhatsapplog FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON whatsapp_enviowhatsapplog;
CREATE POLICY tenant_isolation ON whatsapp_enviowhatsapplog
    USING (empresa_id = current_empresa_id())
    WITH CHECK (empresa_id = current_empresa_id());

-- campanhas_contato
ALTER TABLE campanhas_contato ENABLE ROW LEVEL SECURITY;
ALTER TABLE campanhas_contato FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON campanhas_contato;
CREATE POLICY tenant_isolation ON campanhas_contato
    USING (empresa_id = current_empresa_id())
    WITH CHECK (empresa_id = current_empresa_id());

-- campanhas_segmento
ALTER TABLE campanhas_segmento ENABLE ROW LEVEL SECURITY;
ALTER TABLE campanhas_segmento FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON campanhas_segmento;
CREATE POLICY tenant_isolation ON campanhas_segmento
    USING (empresa_id = current_empresa_id())
    WITH CHECK (empresa_id = current_empresa_id());

-- campanhas_campanha
ALTER TABLE campanhas_campanha ENABLE ROW LEVEL SECURITY;
ALTER TABLE campanhas_campanha FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON campanhas_campanha;
CREATE POLICY tenant_isolation ON campanhas_campanha
    USING (empresa_id = current_empresa_id())
    WITH CHECK (empresa_id = current_empresa_id());

-- campanhas_destinatariocampanha (vinculada à campanha, não tem empresa_id direto)
-- Usa JOIN com campanha para isolamento
ALTER TABLE campanhas_destinatariocampanha ENABLE ROW LEVEL SECURITY;
ALTER TABLE campanhas_destinatariocampanha FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON campanhas_destinatariocampanha;
CREATE POLICY tenant_isolation ON campanhas_destinatariocampanha
    USING (
        EXISTS (
            SELECT 1 FROM campanhas_campanha c
            WHERE c.id = campanhas_destinatariocampanha.campanha_id
              AND c.empresa_id = current_empresa_id()
        )
    );
