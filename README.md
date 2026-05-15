# Mala Direta TCE/AL

Aplicação de mala direta usando `FastAPI` no backend e `PostgreSQL 17` como banco principal, com envio via SMTP `smtp.tceal.tc.br:587` usando STARTTLS.

## Configuração por `.env`

Crie um arquivo `.env` na raiz do projeto. Exemplo:

```env
APP_HOST=0.0.0.0
APP_PORT=8086
APP_TIMEZONE=America/Maceio

POSTGRES_DB=mala_direta
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/mala_direta

ADMIN_EMAILS=admin@tceal.tc.br,fulano@tceal.tc.br
APP_MASTER_KEY=

IMAP_SERVER=smtp.tceal.tc.br
IMAP_PORT=993
IMAP_MAILBOX=INBOX
IMAP_BOUNCE_WINDOW_SECONDS=900
IMAP_BOUNCE_POLL_SECONDS=60
```

Com isso:

- o `docker compose` passa a ler o `.env`
- a aplicação também lê o `.env` quando roda fora do Docker
- a lista de administradores fica centralizada em `ADMIN_EMAILS`

## Como abrir localmente

Com o `.env` pronto e um `DATABASE_URL` válido, rode:

```bash
python3 app.py
```

Depois acesse:

```text
http://127.0.0.1:8086
```

## Como rodar em Docker

### Com Docker Compose

```bash
docker compose up --build
```

Depois acesse:

```text
http://127.0.0.1:8086
```

Para rodar em segundo plano:

```bash
docker compose up --build -d
```

Para parar:

```bash
docker compose down
```

### Com Docker puro

```bash
docker build -t mala-direta-tceal .
docker run --rm -p 8086:8086 --name mala-direta-tceal mala-direta-tceal
```

O `compose` já sobe com:

- aplicação `FastAPI`
- banco `PostgreSQL 17`
- persistência do banco em volume Docker
- pasta local `data/` montada no container para relatórios, chave da aplicação e migração do SQLite legado

## Recursos

- Login com usuário `@tceal.tc.br` pré-fixado.
- Importação de destinatários por CSV, TXT ou digitação manual.
- Upload de anexo para envio junto com a campanha.
- CSV com personalização por colunas, usando marcadores como `{{nome}}`, `{{email}}` e `{{cargo}}`.
- Delay aleatório entre entregas.
- Pausa automática por lote.
- Limite máximo de envios por hora.
- Espaçamento extra automático para domínios Microsoft.
- Pausar, retomar e cancelar campanha em andamento.
- Agendamento de campanha para data e hora futura.
- Histórico local das campanhas com relatório CSV por envio.
- Retry assistido apenas com os e-mails que falharam no envio, com edição manual antes do reenvio.
- Lista de supressão para falhas permanentes.
- Monitoramento de retornos por IMAP após o envio, para detectar bounces no Zimbra.
- Banco principal em `PostgreSQL 17`.
- Migração automática inicial a partir do `data/mala_direta.db`, quando esse arquivo existir e o PostgreSQL ainda estiver vazio.
- Chave local em `data/app.key` para cifrar a senha das campanhas agendadas.
- Validação e remoção de e-mails duplicados antes do envio.
- Senha mantida em memória para envios imediatos e armazenada cifrada apenas quando a campanha é agendada.

## Persistência

- O banco principal agora é o PostgreSQL definido em `DATABASE_URL`.
- Campanhas agendadas ficam salvas no banco e são recuperadas quando a aplicação reinicia.
- A senha usada nessas campanhas é armazenada cifrada localmente.
- Se quiser controlar a cifra com uma chave definida por você, configure `APP_MASTER_KEY` no ambiente antes de subir a aplicação.
- O monitoramento IMAP usa, por padrão, `IMAP_SERVER=smtp.tceal.tc.br`, `IMAP_PORT=993`, caixa `INBOX`, janela de 900 segundos e intervalo de 60 segundos. Esses valores podem ser ajustados por ambiente.

## Stack atual

- Backend: `FastAPI`
- Servidor ASGI: `uvicorn`
- Banco: `PostgreSQL 17`
- Driver PostgreSQL: `psycopg 3`
- Frontend: HTML/CSS/JavaScript servido pela própria aplicação

## CSV esperado

O CSV pode ter uma coluna `email`:

```csv
email,nome,cargo
pessoa@dominio.gov.br,Ana Silva,Diretora
outra@dominio.gov.br,Carlos Lima,Assessor
```

No corpo da mensagem, use:

```text
Olá {{nome}},

Mensagem da campanha.
```

## Ritmo recomendado

Para reduzir risco de bloqueio por política de rate, comece com valores conservadores:

- Delay mínimo: 20 segundos
- Delay máximo: 45 segundos
- Pausa a cada: 25 envios
- Duração da pausa: 300 segundos
- Limite por hora: 90

Esses valores podem ser ajustados conforme orientação da equipe de infraestrutura.
