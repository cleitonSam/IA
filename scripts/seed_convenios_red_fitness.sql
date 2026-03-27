-- Script para preencher convênios das unidades Red Fitness
-- Baseado nos dados da planilha fornecida pelo cliente
-- Execute: psql $DATABASE_URL -f scripts/seed_convenios_red_fitness.sql

UPDATE unidades
SET convenios = '{"gympass_wellhub": "Basic+", "totalpass": "TP1+", "outros": ""}'::jsonb
WHERE nome ILIKE '%Bergamini%';

UPDATE unidades
SET convenios = '{"gympass_wellhub": "Basic+", "totalpass": "TP1+", "outros": ""}'::jsonb
WHERE nome ILIKE '%Mandaqui%';

UPDATE unidades
SET convenios = '{"gympass_wellhub": "Basic+", "totalpass": "TP1+", "outros": ""}'::jsonb
WHERE nome ILIKE '%Ourinhos%';

UPDATE unidades
SET convenios = '{"gympass_wellhub": "Basic+", "totalpass": "TP1+", "outros": ""}'::jsonb
WHERE nome ILIKE '%Andorinha%';

UPDATE unidades
SET convenios = '{"gympass_wellhub": "Basic+", "totalpass": "TP2", "outros": ""}'::jsonb
WHERE nome ILIKE '%Ricardo Jafet%';

UPDATE unidades
SET convenios = '{"gympass_wellhub": "Basic+", "totalpass": "TP1+", "outros": ""}'::jsonb
WHERE nome ILIKE '%Indaiatuba%';

-- Confirma o resultado
SELECT nome, convenios FROM unidades WHERE nome ILIKE '%Red Fitness%' ORDER BY nome;
