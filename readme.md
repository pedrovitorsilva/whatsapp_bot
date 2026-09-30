# Escalas no WhatsApp — WAHA + n8n + Google Sheets (low-code, uso pessoal)

## 1. O que é

Uma planilha com a escala. Na **quinta-feira à noite**, a mensagem **completa** com a escala da **semana seguinte (segunda a domingo)** sai no grupo. Na **sexta e no sábado**, saem **lembretes curtos, marcando (`@`) as pessoas escaladas**. Os dias e horários são definidos por cron. Se alguém marcar o bot (`@bot`) no grupo, ele responde marcando a pessoa com a próxima data dela.

## 2. Papéis

| Necessidade | Quem faz |
|---|---|
| Sessão, QR, envio, receber mensagens | **WAHA** |
| Cron, lógica da escala, planilha, alertas | **n8n** (Schedule Trigger, Google Sheets, Code, IF, Wait, Telegram/Email) |
| Dados e interface de administração | **Google Sheets** |
| Idempotência | Aba `Envios` |

## 3. Arquitetura

```
      rede interna do Docker (nada exposto à internet)
┌────────────────────────────────────────────────────────────┐
│  n8n  ───── POST http://waha:3000/api/sendText ─────▶  WAHA ───▶ Grupo
│   ▲                                                    │   |    WhatsApp
│   └──── webhook http://n8n:5678/webhook/<segredo> ◀────┘   |
│   │                                                        |
└───┼────────────────────────────────────────────────────────┘
    ▼
 Google Sheets (API, conta de serviço)
```

Como WAHA e n8n se falam **pela rede interna**, não é preciso URL pública nem túnel. Publique as portas só em `127.0.0.1` e acesse pelo navegador local (ou por túnel SSH se estiver em servidor).

## 4. Docker

`docker-compose.yml`:

```yaml
services:
  waha:
    image: devlikeapro/waha:<TAG_FIXA>            # não usar latest
    restart: unless-stopped
    ports: ["127.0.0.1:3000:3000"]                # dashboard/Swagger só local
    environment:
      WHATSAPP_DEFAULT_ENGINE: NOWEB              # sem Chromium, leve
      WAHA_API_KEY: ${WAHA_API_KEY}
      WAHA_DASHBOARD_USERNAME: ${DASH_USER}
      WAHA_DASHBOARD_PASSWORD: ${DASH_PASS}
      WHATSAPP_START_SESSION: default
      WHATSAPP_HOOK_URL: http://n8n:5678/webhook/${HOOK_SECRET}
      WHATSAPP_HOOK_EVENTS: message
    volumes:
      - ./waha-sessions:/app/.sessions            # sessão do WhatsApp (credencial!)

  n8n:
    image: n8nio/n8n:<TAG_FIXA>
    restart: unless-stopped
    ports: ["127.0.0.1:5678:5678"]
    environment:
      GENERIC_TIMEZONE: America/Bahia
      TZ: America/Bahia
      N8N_ENCRYPTION_KEY: ${N8N_ENCRYPTION_KEY}   # guarde: sem ela, credenciais viram lixo
    volumes:
      - ./n8n-data:/home/node/.n8n
    depends_on: [waha]
```

`.env` fora do Git (`WAHA_API_KEY`, `DASH_USER`, `DASH_PASS`, `HOOK_SECRET` = string aleatória longa, `N8N_ENCRYPTION_KEY`). Backup de `./waha-sessions` e `./n8n-data`.

## 5. Planilha

Cabeçalhos na linha 1. **Datas como texto (`DD/MM/YYYY`)** e horas como texto (`18:00`): evita problemas de formato ao ler pelo n8n.

- **Pessoas:** `nome | telefone` (só dígitos com DDI, ex.: `5577999990000`)
- **Escalas:** `data | horario | pessoa_nome`
- **Trocas:** `pessoa_original | pessoa_substituta | data_referencia | status` (só `APROVADA` vale). Um Google Forms pode alimentar esta aba.
- **Mensagens:** `tipo | texto`
  - `semanal`: `📅 Escala da semana ({{inicio}} a {{fim}})\n\n{{lista}}\n\nBoa escala a todos!` (quinta; sugestão, ajuste à vontade)
  - `lembrete`: `🔔 Lembrete da escala ({{inicio}} a {{fim}}):\n{{lista}}` (sexta e sábado; cada linha da lista já vem com a pessoa marcada)
  - `proxima`: `{{pessoa}}, sua próxima escala é em {{data}} às {{horario}}.`
  - `sem_escala`: `{{pessoa}}, não encontrei escala futura para você.`
- **Envios** (o n8n escreve): `tipo | data_referencia | status | criado_em | texto`
  - `tipo = completo`: `data_referencia` = a **segunda-feira** da semana avisada (um por semana)
  - `tipo = lembrete`: `data_referencia` = a **data do próprio envio** (um por dia de lembrete)

A troca vale **tanto se você editar o nome direto em `Escalas` quanto se só registrar em `Trocas`**: o workflow só substitui quando `pessoa_original` ainda consta na linha da escala.

**Credencial do Google no n8n:** conta de serviço do Google Cloud (Sheets API ativada), com a planilha compartilhada com o e-mail dela. Funciona sem URL pública, ao contrário do OAuth.

## 6. Workflows

### Cuidados comuns a todos (armadilhas do n8n)

- **Nós *Google Sheets* (Get Row(s)): ligar "Execute Once".** Sem isso, o nó roda uma vez por item recebido.
- **Ligar "Always Output Data"** nos nós que podem vir vazios (`Envios`, `Trocas`). Sem isso, planilha vazia interrompe o fluxo.
- **HTTP Request para o WAHA:** "Retry On Fail" **desligado**, *timeout* 30 s, e na aba Settings "On Error → Continue (using error output)".
- Os workflows precisam estar **ativos** (toggle) para o cron e o webhook de produção funcionarem. O toggle desativado é o seu **kill switch**.

Configuração do HTTP Request (`sendText`), nos dois workflows:

- Método `POST`, URL `http://waha:3000/api/sendText`
- Header `X-Api-Key: <WAHA_API_KEY>` (guardar como credencial *Header Auth*)
- Body JSON: `{ "session": "default", "chatId": "<GROUP_ID>", "text": "...", "mentions": [...] }`

### Workflow A — Aviso semanal (quinta) + lembretes (sexta e sábado)

Um único workflow com **dois gatilhos de cron** que alimentam a mesma cadeia. O cron define **quando** e **qual tipo** de mensagem sai; não há dia da semana fixo dentro do código.

```
Trigger semanal           (Schedule: 0 18-23 * * 4)    → tipo COMPLETO ┐
Trigger lembrete          (Schedule: 0 18-23 * * 5,6)  → tipo LEMBRETE ┴→
  → Sheets: Pessoas       (Execute Once)
  → Sheets: Escalas       (Execute Once)
  → Sheets: Trocas        (Execute Once, Always Output Data)
  → Sheets: Envios        (Execute Once, Always Output Data)
  → Sheets: Mensagens     (Execute Once)
  → Code: montar aviso    (devolve 0 itens se já enviado ou sem escala)
  → Sheets: Append Envios (status = ENVIANDO, texto)      ← registra ANTES de enviar
  → HTTP Request: sendText
       ├─ sucesso → Sheets: Update Envios (match data_referencia → status = ENVIADO)
       └─ erro    → Telegram/Email: alerta  (status permanece ENVIANDO: conferir à mão)
```

- Nomeie os gatilhos exatamente **`Trigger semanal`** e **`Trigger lembrete`** (o código consulta pelo nome qual deles disparou).
- Cada cron roda **de hora em hora entre 18h e 23h** no(s) seu(s) dia(s): se o servidor estiver fora às 18h, a mensagem sai na primeira execução seguinte (*catch-up*).
- A aba `Envios` impede repetição: o completo tem chave `completo` + segunda-feira da semana; cada lembrete tem chave `lembrete` + data do dia. Como as chaves nunca coincidem, o update de `Envios` pode casar só por `data_referencia`.
- **Para mudar dias ou horários**, edite só o cron dos gatilhos (`0` = domingo, `4` = quinta, `5` = sexta, `6` = sábado). A semana avisada é sempre **a seguinte, de segunda a domingo**, tanto no completo quanto nos lembretes.
- **Os lembretes citam a mesma semana da mensagem completa**, marcando quem está escalado nela. Se você quiser que o lembrete mostre só os próximos dias (por exemplo, apenas o fim de semana seguinte), basta ajustar o intervalo `dIni`/`dFim` do ramo `lembrete` no código.
- **No `sendText` de A, use os dados do nó Code, não do item anterior** (o nó Append devolve a linha gravada, sem `mentions`): `text = {{ $('Code: montar aviso').item.json.texto }}`, `mentions = {{ $('Code: montar aviso').item.json.mentions }}`.

Código do nó **Code: montar aviso**:

```js
const pessoas = $('Pessoas').all().map(i => i.json);
const esc = $('Escalas').all().map(i => i.json);
const tr  = $('Trocas').all().map(i => i.json).filter(t => t.status === 'APROVADA');
const env = $('Envios').all().map(i => i.json);
const modelo = t => $('Mensagens').all().map(i => i.json).find(m => m.tipo === t).texto;

const completo = $('Trigger semanal').isExecuted;                // qual cron disparou
const tipo = completo ? 'completo' : 'lembrete';

// semana seguinte: segunda a domingo (Luxon: semana começa na segunda)
const ini = $now.plus({ weeks: 1 }).startOf('week');
const dIni = ini.toISODate(), dFim = ini.plus({ days: 6 }).toISODate();

const chave = completo ? dIni : $now.toISODate();               // completo: 1 por semana; lembrete: 1 por dia
if (env.some(x => x.tipo === tipo && x.data_referencia === chave)) return [];

const dias = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'];
const br = d => d.split('-').reverse().slice(0, 2).join('/');
const quando = e => `${dias[DateTime.fromISO(e.dia).weekday - 1]} ${br(e.dia)} — ${e.horario}`;

const efet = esc.filter(e => e.data >= dIni && e.data <= dFim)
  .sort((a, b) => (a.data + a.horario).localeCompare(b.data + b.horario))
  .map(e => {
    const t = tr.find(t => t.pessoa_original === e.pessoa_nome && t.data_referencia === e.data);
    return { dia: e.data, horario: e.horario, nome: t ? t.pessoa_substituta : e.pessoa_nome };
  });
if (!efet.length) return [];

const fone = nome => String(pessoas.find(p => p.nome === nome)?.telefone ?? '').replace(/\D/g, '');
const mentions = [];
let lista;
if (completo) {
  lista = efet.map(e => `${quando(e)} — ${e.nome}`).join('\n');          // completo: sem menções
} else {
  lista = efet.map(e => {
    const n = fone(e.nome);
    if (n) mentions.push(n + '@c.us');
    return `${n ? '@' + n : e.nome} — ${quando(e)}`;                    // sem telefone: só o nome
  }).join('\n');
}

const texto = modelo(completo ? 'semanal' : 'lembrete')
  .replace('{{inicio}}', br(dIni)).replace('{{fim}}', br(dFim)).replace('{{lista}}', lista);
return [{ json: { tipo, data_referencia: chave, status: 'ENVIANDO', criado_em: $now.toISO(),
                  texto, mentions: [...new Set(mentions)] } }];
```

No nó **Append Envios**, mapeie as colunas manualmente (`tipo`, `data_referencia`, `status`, `criado_em`, `texto`); `mentions` não é gravada na planilha.

### Workflow B — Resposta a menções

```
Webhook (POST, path = <HOOK_SECRET>)              ← recebe o evento `message` do WAHA
  → Code: filtrar          (0 itens se não for o caso)
  → Sheets: Pessoas / Escalas / Trocas / Mensagens (Execute Once)
  → Code: responder        (monta texto e menção)
  → Wait (aleatório 3–8 s: ex.: expressão {{ 3 + Math.random()*5 }} segundos)
  → HTTP Request: sendText (com "mentions")
       └─ erro → Telegram/Email: alerta
```

Código do nó **Code: filtrar**:

```js
const m = $json.body?.payload ?? {};
const BOT = '<NUMERO_DO_BOT>';
const GROUP = '<GROUP_ID>';

if (!m.id || m.fromMe || m.from !== GROUP) return [];

// deduplica reentrega do webhook (só vale com o workflow ativo)
const s = $getWorkflowStaticData('global');
s.vistos ??= [];
if (s.vistos.includes(m.id)) return [];
s.vistos = [...s.vistos.slice(-200), m.id];

const marcado = (m.mentionedIds ?? []).some(x => String(x).includes(BOT)) || String(m.body).includes('@' + BOT);
if (!marcado) return [];

const num = String(m.participant ?? m.author ?? '').replace(/\D/g, '');
return [{ json: { num } }];
```

Código do nó **Code: responder**:

```js
const num = $('Code: filtrar').first().json.num;
const pessoa = $('Pessoas').all().map(i => i.json).find(p => String(p.telefone).replace(/\D/g, '') === num);
if (!pessoa) return [];                                          // remetente desconhecido: silêncio

const tr  = $('Trocas').all().map(i => i.json).filter(t => t.status === 'APROVADA');
const msg = t => $('Mensagens').all().map(i => i.json).find(m => m.tipo === t).texto;
const hoje = $now.toISODate();

const prox = $('Escalas').all().map(i => i.json)
  .map(e => {
    const t = tr.find(t => t.pessoa_original === e.pessoa_nome && t.data_referencia === e.data);
    return { dia: e.data, horario: e.horario, nome: t ? t.pessoa_substituta : e.pessoa_nome };
  })
  .filter(e => e.nome === pessoa.nome && e.dia >= hoje)
  .sort((a, b) => a.dia.localeCompare(b.dia))[0];

const texto = (prox ? msg('proxima') : msg('sem_escala'))
  .replace('{{pessoa}}', '@' + num)
  .replace('{{data}}', prox ? prox.dia.split('-').reverse().join('/') : '')
  .replace('{{horario}}', prox ? prox.horario : '');
return [{ json: { texto, mentions: [num + '@c.us'] } }];
```

No `sendText` do workflow B: `text = {{ $json.texto }}`, `mentions = {{ $json.mentions }}`.

### Workflow C — Alertas de erro

`Error Trigger` → **Telegram** (ou Email). Em *Settings* de cada workflow A e B, definir este como "Error Workflow". O alerta sai por **canal diferente do WhatsApp**, para funcionar se o número cair.

Opcional: workflow D com Schedule (a cada 30 min) chamando `GET http://waha:3000/api/sessions/default` e alertando se `status` ≠ `WORKING` (sessão caiu ou precisa de novo QR).

## 7. Passo a passo

1. `docker compose up -d`. Abrir `http://localhost:3000` (dashboard do WAHA) e **parear o chip dedicado** (QR). Sessão `default` em `WORKING`.
2. Adicionar o número do bot ao grupo. Pegar o `GROUP_ID` (`...@g.us`) no Swagger do WAHA (`http://localhost:3000`, listagem de chats/grupos).
3. Abrir `http://localhost:5678`, criar a conta do n8n e as credenciais: Google (conta de serviço), Header Auth do WAHA, Telegram.
4. Criar a planilha (seção 5) e os workflows A, B e C (seção 6). Preencher `GROUP_ID` e `NUMERO_DO_BOT` nos nós.
5. **Testar antes de ativar:** executar A manualmente com escalas cadastradas para a semana seguinte; para B, ativar o workflow e marcar o bot no grupo.
6. Ativar os workflows.

Se o n8n rodar em servidor remoto, acesse as duas UIs por túnel SSH (`ssh -L 5678:localhost:5678 -L 3000:localhost:3000 usuario@servidor`).

## 8. Cuidados

- **Risco de banimento existe:** o WAHA (NOWEB) é conexão não oficial. Use **chip dedicado**, só o grupo onde o número já está, 1 mensagem completa + 2 lembretes curtos por semana e resposta somente quando marcado (o filtro do workflow B já restringe ao grupo). A espera aleatória do nó Wait dá ritmo humano.
- **Envio duplo é pior que envio ausente:** por isso `ENVIANDO` é gravado antes de enviar e não há *retry*. Se sobrar linha `ENVIANDO` em `Envios`, confira o grupo. O texto pronto está na coluna `texto` (modo degradado: copie e cole).
- **Segredos:** `.env` e as pastas `waha-sessions`/`n8n-data` fora do Git; `waha-sessions` equivale a uma senha do WhatsApp. Sem `N8N_ENCRYPTION_KEY` guardada, as credenciais do n8n não se recuperam.
- **Portas em `127.0.0.1`:** nenhum dos dois serviços fica aberto à internet.
- **Versões fixas** nas imagens; leia o *changelog* antes de atualizar.
- **Dados pessoais:** a planilha tem nomes e telefones; compartilhe só com quem administra.

## 9. Confirmar antes de depender (não verifiquei)

- **Payload de menção no webhook:** o filtro aceita `mentionedIds` **ou** `@<numero>` no texto. Marque o bot no grupo de teste e veja o payload real na execução do n8n.
- **Parâmetro `mentions` do `sendText`:** conferir nome e formato no Swagger do WAHA, e se uma lista **vazia** (mensagem completa, sem menções) é aceita; se não for, omita o campo nesse caso.
- **`$('Trigger semanal').isExecuted` (workflow A):** confirmar que funciona na sua versão do n8n. Se não, alternativa: gravar `modo` em um nó *Set* logo após cada gatilho e lê-lo no Code.
- **Remetente em LID:** se `participant` vier como `...@lid`, o telefone não casa com `Pessoas`. Solução: coluna `lid` em `Pessoas` e casar por ela.
- **Nós prontos do WAHA para n8n:** existe um nó comunitário do WAHA; ele pode substituir o HTTP Request, mas o HTTP Request funciona sem instalar nada e foi o usado aqui.
- **Nomes de variáveis de ambiente** do WAHA e caminhos de volume: conferir na documentação da versão fixada.
- **Nomes de campos do n8n** (ex.: `$now`, `$getWorkflowStaticData`) valem para versões recentes; conferir na versão fixada.
