# Mala Direta TCE/AL

Aplicação local para envio de mala direta usando o SMTP `smtp.tceal.tc.br:587` com STARTTLS.

## Como abrir localmente

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

O container já sobe com `APP_HOST=0.0.0.0` e `APP_PORT=8086`.

## Recursos

- Login com usuário `@tceal.tc.br` pré-fixado.
- Importação de destinatários por CSV, TXT ou digitação manual.
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
- Banco SQLite local em `data/mala_direta.db` para persistir histórico e supressões.
- Chave local em `data/app.key` para cifrar a senha das campanhas agendadas.
- Validação e remoção de e-mails duplicados antes do envio.
- Senha mantida em memória para envios imediatos e armazenada cifrada apenas quando a campanha é agendada.

## Persistência

- Campanhas agendadas ficam salvas no banco e são recuperadas quando a aplicação reinicia.
- A senha usada nessas campanhas é armazenada cifrada localmente.
- Se quiser controlar a cifra com uma chave definida por você, configure `APP_MASTER_KEY` no ambiente antes de subir a aplicação.
- O monitoramento IMAP usa, por padrão, `IMAP_SERVER=smtp.tceal.tc.br`, `IMAP_PORT=993`, caixa `INBOX`, janela de 900 segundos e intervalo de 60 segundos. Esses valores podem ser ajustados por ambiente.

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
