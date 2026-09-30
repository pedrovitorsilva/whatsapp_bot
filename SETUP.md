# SETUP — subir e testar localmente

Especificação completa no `readme.md`. Aqui só a ordem de execução. Comandos em Git Bash, a partir desta pasta.

Versões fixadas: `devlikeapro/waha:noweb-2026.9.1` (Core, engine NOWEB) e `n8nio/n8n:2.40.7`.

O `.env` já foi gerado com os segredos (`WAHA_API_KEY`, `DASH_USER`, `DASH_PASS`, `HOOK_SECRET`,
`N8N_ENCRYPTION_KEY`). **Faça backup dele**: sem `N8N_ENCRYPTION_KEY` as credenciais do n8n não se
recuperam. Os campos `SHEET_ID`, `GROUP_ID`, `NUMERO_DO_BOT`, `ALERT_EMAIL` você preenche nos passos abaixo.

## 1. Subir

```bash
docker compose up -d
docker compose ps          # waha e n8n "running"
```

## 2. Parear o WhatsApp (QR)

1. Abra http://localhost:3000 → login com `DASH_USER` / `DASH_PASS` do `.env`.
2. Se o dashboard pedir a conexão com o servidor: URL `http://localhost:3000`, API Key = `WAHA_API_KEY`.
3. Sessão `default` → botão de QR (câmera). No celular do **chip dedicado**: WhatsApp → *Aparelhos conectados* → *Conectar aparelho* → escaneie.
4. Confirme (deve mostrar `"status": "WORKING"` e, em `me.id`, o número do bot):

```bash
source .env
curl -s -H "X-Api-Key: $WAHA_API_KEY" http://localhost:3000/api/sessions/default

ou

$env:WAHA_API_KEY = (Get-Content .env | Select-String "WAHA_API_KEY").ToString().Split("=")[1]

curl.exe -s -H "X-Api-Key: $env:WAHA_API_KEY" http://localhost:3000/api/sessions/default
```

5. Copie os dígitos de `me.id` (ex.: `5577999990000@c.us` → `5577999990000`) para `NUMERO_DO_BOT` no `.env`,
   e os de `me.lid` (ex.: `143663116071120@lid` → `143663116071120`) para `BOT_LID` — em grupos que usam LID
   a menção ao bot chega por ele, não pelo número.

## 3. Pegar o GROUP_ID

```bash
curl -s -H "X-Api-Key: $WAHA_API_KEY" "http://localhost:3000/api/default/groups" | python -m json.tool | grep -E '"(id|subject)"'
  
ou  
  
curl.exe -s -H "X-Api-Key: $env:WAHA_API_KEY" "http://localhost:3000/api/default/groups" |
    python -m json.tool |
    Select-String '"(id|subject)"'    
```

(ou no Swagger em http://localhost:3000 → *Authorize* com a API key → `GET /api/{session}/groups`).
Copie o `...@g.us` do grupo para `GROUP_ID` no `.env`.

## 4. Conta de serviço do Google (GCP Console)

1. https://console.cloud.google.com → crie (ou escolha) um projeto.
2. *APIs e serviços → Biblioteca* → **Google Sheets API** → *Ativar*.
3. *IAM e administrador → Contas de serviço → Criar conta de serviço* (ex.: `n8n-escalas`). Não precisa de papel/role.
4. Abra a conta criada → aba *Chaves* → *Adicionar chave → Criar nova chave → JSON*. Guarde o arquivo (é segredo; não coloque nesta pasta).
5. Na planilha: *Compartilhar* → cole o e-mail da conta (`...@...iam.gserviceaccount.com`) como **Editor**, sem notificar.

## 5. Planilha

`SHEET_ID` é o trecho da URL entre `/d/` e `/edit` → coloque no `.env`.

Abas e cabeçalhos na **linha 1**. O código lê cabeçalhos e os valores de `Tipo`/`Status` em
minúsculas com espaço → `_` (`Data de Referência` → `data_de_referência`, `Sem Escala` → `sem_escala`),
então maiúsculas não importam, mas acentos sim.

| Aba | Cabeçalhos |
|---|---|
| `Pessoas` | `Nome`, `Função`, `Telefone` (só dígitos com DDI) |
| `Escala` | `Nome`, `Data`, `Horário`, `Função` (`Liderança` / `Volante` / `Membro`) |
| `Trocas` | `Pessoa Original`, `Pessoa Substituta`, `Data de Referência`, `Status` (`Aprovada` vale) |
| `Mensagens` | `Tipo`, `Mensagem` |
| `Envios` | `Tipo`, `Data de Referência`, `Status`, `Criado Em`, `Texto` (nomes exatos: o n8n escreve nelas) |

Datas no formato `dd/mm/aaaa` (data normal do Sheets serve).

`Mensagens` — tipos `Semanal`, `Lembrete`, `Próxima`, `Sem Escala`. Placeholders `{{...}}`:

| Tipo | Placeholders |
|---|---|
| `Semanal` | `{{data}}` (dd/mm do culto), `{{Lideranças}}`, `{{Volantes}}`, `{{Membros}}` (marcados com @, separados por vírgula) |
| `Lembrete` | `{{data}}`, `{{lista}}` (todos do culto, marcados com @) |
| `Próxima` | `{{pessoa}}`, `{{data}}`, `{{horario}}` |
| `Sem Escala` | `{{pessoa}}` |

"Culto" = a primeira data da `Escala` entre hoje e hoje+6. Dados de teste: um culto nessa janela com seu nome.

## 6. n8n: conta e credenciais

Abra http://localhost:5678 e crie a conta de owner. Depois, em *Credentials → Create*, crie **exatamente uma** de cada:

| Tipo | Nome sugerido | Campos |
|---|---|---|
| **Google Service Account API** | `Google Sheets (conta de serviço)` | *Service Account Email* e *Private Key* = `client_email` e `private_key` do JSON do passo 4 (cole a chave inteira, com `-----BEGIN...`) |
| **Header Auth** | `WAHA API Key` | Name `X-Api-Key`, Value = `WAHA_API_KEY` do `.env` |
| **SMTP** | `SMTP alertas` | do seu provedor. Gmail: host `smtp.gmail.com`, porta `465`, SSL ligado, usuário = seu e-mail, senha = [senha de app](https://myaccount.google.com/apppasswords) |

Preencha `ALERT_EMAIL` no `.env` (remetente e destinatário dos alertas; com Gmail use o mesmo e-mail do SMTP).

## 7. Importar os workflows

```bash
python import_workflows.py
```

O script confere o `.env`, pega os IDs das 3 credenciais no n8n, preenche `SHEET_ID`, `GROUP_ID`,
`NUMERO_DO_BOT`, `HOOK_SECRET`, `ALERT_EMAIL` nos JSONs de `workflows-json/` e importa os três:

- **Escalas A - Aviso semanal e lembretes**
- **Escalas B - Resposta a menções**
- **Escalas C - Alertas de erro**

A e B já vêm com C definido como *Error Workflow* (confira em *Settings* de cada um). Reimportar
sobrescreve os workflows (IDs fixos) — edições feitas na UI se perdem; edite os JSONs ou pare de reimportar.

## 8. Testar (antes de publicar)

**A — aviso semanal.** Abra o workflow A e clique em ▶ no nó `Trigger semanal` (executa a partir dele).
Esperado: aviso do próximo culto no grupo e linha em `Envios` com `semanal`, a data do culto e `ENVIADO`.
Depois ▶ em `Trigger lembrete`: lembrete com todos do culto marcados; linha `lembrete` + data de hoje.

- Para repetir um teste, apague a linha correspondente em `Envios` (ela é o que impede o reenvio).
- Se o Code acusar erro em `$('Trigger semanal').isExecuted`, aplique a alternativa do README §9 (nó *Set* com `modo` após cada gatilho).
- Se o WAHA recusar `mentions`, confira o formato no Swagger (`POST /api/sendText`). O campo já é omitido quando a lista é vazia.

**B — menção.** O webhook de produção só responde com o workflow publicado: clique em **Publish** no B,
e no grupo, de outro número (o seu), mande `@bot` marcando o número do bot. Em *Executions*, abra a execução e confira o
payload que entrou em `Code: filtrar` (README §9):

- `payload.mentionedIds` / `payload.body` contêm o `NUMERO_DO_BOT`? Se a menção vier como `...@lid`, o filtro não casa: ajuste `BOT` no código.
- `payload.participant` vem como `...@c.us` ou `...@lid`? Se `@lid`, o telefone não casa com `Pessoas` → adicionar coluna `lid` (README §9).
- Execução que para em `Code: filtrar` / `Code: responder` sem saída = filtro descartou (não é erro).

**C — alertas.**
- *Falha de envio* (alerta dentro de A/B): `docker compose stop waha`, apague as linhas de teste de `Envios`, rode A manualmente.
  Esperado: e-mail "Falha no envio" e linha `ENVIANDO` em `Envios` (apague depois). `docker compose start waha`.
- *Erro de workflow* (Workflow C): o n8n só dispara o Error Workflow em execuções de produção, não nas manuais.
  Com B publicado, renomeie a aba `Pessoas` para `Pessoas_x`, marque o bot no grupo → e-mail "Erro no workflow". Renomeie de volta.

## 9. Ativar

Clique **Publish** em A e B. C não precisa ser publicado (o Error Workflow roda chamado por A/B). Despublicar = kill switch.

Backup: `.env`, `waha-sessions/` (equivale à senha do WhatsApp) e `n8n-data/`.
