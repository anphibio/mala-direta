from __future__ import annotations

import csv
import html
import io
import json
import os
import random
import re
import smtplib
import ssl
import threading
import time
import uuid
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from string import Template
from typing import Any


SMTP_SERVER = "smtp.tceal.tc.br"
SMTP_PORT = 587
EMAIL_DOMAIN = "@tceal.tc.br"
APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8086"))

EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


@dataclass
class Recipient:
    email: str
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class FormFile:
    filename: str
    value: bytes


@dataclass
class FormData:
    fields: dict[str, list[str]] = field(default_factory=dict)
    files: dict[str, FormFile] = field(default_factory=dict)


@dataclass
class MailJob:
    id: str
    sender: str
    total: int
    subject: str
    status: str = "running"
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    current: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    next_send_at: float | None = None
    logs: list[dict[str, Any]] = field(default_factory=list)
    pause_event: threading.Event = field(default_factory=threading.Event)
    cancel_event: threading.Event = field(default_factory=threading.Event)


JOB_LOCK = threading.Lock()
CURRENT_JOB: MailJob | None = None


INDEX_HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mala Direta TCE/AL</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #1d2733;
      --muted: #667085;
      --line: #d7dde5;
      --blue: #205493;
      --green: #246b4f;
      --red: #9f2d20;
      --amber: #8a5a00;
      --soft-blue: #e8f1fb;
      --soft-green: #e8f5ef;
      --shadow: 0 12px 28px rgba(29, 39, 51, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    header {
      background: #ffffff;
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      z-index: 5;
    }
    .bar {
      max-width: 1220px;
      margin: 0 auto;
      padding: 18px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    h1 {
      font-size: 22px;
      line-height: 1.15;
      margin: 0;
      letter-spacing: 0;
    }
    .server {
      color: var(--muted);
      font-size: 14px;
      white-space: nowrap;
    }
    main {
      max-width: 1220px;
      margin: 0 auto;
      padding: 24px;
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(340px, .75fr);
      gap: 18px;
      align-items: start;
    }
    section, aside {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .form {
      padding: 22px;
      display: grid;
      gap: 18px;
    }
    .panel-title {
      margin: 0 0 12px;
      font-size: 16px;
      font-weight: 750;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }
    label {
      display: grid;
      gap: 7px;
      color: #2d3748;
      font-size: 13px;
      font-weight: 700;
    }
    input, textarea, select {
      width: 100%;
      border: 1px solid #c6ced8;
      border-radius: 6px;
      padding: 11px 12px;
      font: inherit;
      font-size: 14px;
      color: var(--ink);
      background: #fff;
      outline: none;
    }
    input:focus, textarea:focus, select:focus {
      border-color: var(--blue);
      box-shadow: 0 0 0 3px rgba(32, 84, 147, .14);
    }
    textarea { min-height: 160px; resize: vertical; line-height: 1.45; }
    .prefix {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
    }
    .prefix input {
      border-radius: 6px 0 0 6px;
    }
    .prefix span {
      border: 1px solid #c6ced8;
      border-left: 0;
      padding: 11px 12px;
      min-height: 43px;
      display: flex;
      align-items: center;
      border-radius: 0 6px 6px 0;
      color: var(--muted);
      background: #f8fafc;
      font-size: 14px;
    }
    .tabs {
      display: inline-grid;
      grid-template-columns: repeat(3, 1fr);
      background: #eef2f6;
      border-radius: 7px;
      padding: 3px;
      gap: 3px;
      width: min(100%, 520px);
    }
    .tab {
      border: 0;
      border-radius: 5px;
      background: transparent;
      padding: 9px 12px;
      color: #465464;
      font-weight: 750;
      cursor: pointer;
    }
    .tab.active {
      background: #fff;
      color: var(--blue);
      box-shadow: 0 1px 4px rgba(29, 39, 51, .10);
    }
    .hidden { display: none !important; }
    .hint {
      color: var(--muted);
      font-size: 13px;
      font-weight: 500;
      line-height: 1.45;
    }
    .checks {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      align-items: center;
    }
    .check {
      display: flex;
      grid-template-columns: none;
      align-items: center;
      gap: 8px;
      font-weight: 700;
    }
    .check input { width: 18px; height: 18px; }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      border-top: 1px solid var(--line);
      padding-top: 18px;
    }
    button {
      min-height: 42px;
      border: 1px solid #aeb8c4;
      background: #fff;
      color: var(--ink);
      border-radius: 6px;
      padding: 0 14px;
      font: inherit;
      font-size: 14px;
      font-weight: 750;
      cursor: pointer;
    }
    button.primary {
      background: var(--blue);
      border-color: var(--blue);
      color: white;
    }
    button.danger {
      border-color: #d7aaa5;
      color: var(--red);
    }
    button:disabled {
      opacity: .55;
      cursor: not-allowed;
    }
    aside {
      position: sticky;
      top: 82px;
      padding: 18px;
      display: grid;
      gap: 16px;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
    }
    .stat {
      border: 1px solid var(--line);
      background: #fbfcfe;
      border-radius: 7px;
      padding: 12px;
      min-height: 78px;
    }
    .stat strong {
      display: block;
      font-size: 25px;
      line-height: 1;
      margin-bottom: 8px;
    }
    .stat span {
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
      text-transform: uppercase;
    }
    .status {
      border-radius: 7px;
      padding: 12px;
      background: var(--soft-blue);
      color: #173f6b;
      font-weight: 750;
      line-height: 1.4;
    }
    .status.done { background: var(--soft-green); color: var(--green); }
    .status.error { background: #fff1ef; color: var(--red); }
    .status.paused { background: #fff7df; color: var(--amber); }
    .progress {
      height: 10px;
      border-radius: 999px;
      background: #e6ebf1;
      overflow: hidden;
    }
    .progress > div {
      height: 100%;
      width: 0;
      background: var(--green);
      transition: width .25s ease;
    }
    .log {
      border: 1px solid var(--line);
      border-radius: 7px;
      height: 280px;
      overflow: auto;
      background: #0f1720;
      color: #d6e2ef;
      padding: 12px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.55;
    }
    .preview {
      border: 1px solid var(--line);
      background: #fbfcfe;
      border-radius: 7px;
      padding: 12px;
      min-height: 46px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .editor-shell {
      border: 1px solid #c6ced8;
      border-radius: 6px;
      overflow: hidden;
      background: #fff;
    }
    .editor-toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 10px;
      background: #f8fafc;
      border-bottom: 1px solid var(--line);
    }
    .tool-btn {
      min-height: 34px;
      padding: 0 12px;
      border-radius: 5px;
      font-size: 13px;
      border: 1px solid #c6ced8;
      background: #fff;
    }
    .html-editor {
      min-height: 180px;
      padding: 12px;
      outline: none;
      line-height: 1.5;
      font-size: 14px;
    }
    .html-editor:empty:before {
      content: "Digite aqui a mensagem da mala direta.";
      color: var(--muted);
    }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; padding: 14px; }
      aside { position: static; }
      .bar { align-items: flex-start; flex-direction: column; padding: 15px; }
      .server { white-space: normal; }
      .grid { grid-template-columns: 1fr; }
      .form { padding: 16px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <div>
        <h1>Mala Direta TCE/AL</h1>
        <div class="hint">Envio autenticado com controles de ritmo, fila e personalização por CSV.</div>
      </div>
      <div class="server">SMTP: smtp.tceal.tc.br:587 STARTTLS</div>
    </div>
  </header>

  <main>
    <section>
      <form id="mailForm" class="form">
        <div>
          <p class="panel-title">Acesso de envio</p>
          <div class="grid">
            <label>
              Usuário
              <div class="prefix">
                <input name="username" autocomplete="username" required placeholder="seu.usuario">
                <span>@tceal.tc.br</span>
              </div>
            </label>
            <label>
              Senha
              <input type="password" name="password" autocomplete="current-password" required placeholder="Senha do e-mail">
            </label>
          </div>
        </div>

        <div>
          <p class="panel-title">Destinatários</p>
          <div class="tabs" role="tablist">
            <button type="button" class="tab active" data-target="csvBox">CSV</button>
            <button type="button" class="tab" data-target="txtBox">TXT</button>
            <button type="button" class="tab" data-target="manualBox">Informar</button>
          </div>
          <div id="csvBox" class="sourceBox">
            <label>
              Arquivo CSV
              <input type="file" name="csv_file" accept=".csv,text/csv">
            </label>
            <div class="hint">O CSV pode ter uma coluna chamada email, e outras colunas podem ser usadas como {{nome}}, {{cargo}} ou similares.</div>
          </div>
          <div id="txtBox" class="sourceBox hidden">
            <label>
              Arquivo TXT
              <input type="file" name="txt_file" accept=".txt,text/plain">
            </label>
            <div class="hint">O TXT aceita e-mails separados por linha, vírgula, ponto e vírgula ou espaço.</div>
          </div>
          <div id="manualBox" class="sourceBox hidden">
            <label>
              E-mails
              <textarea name="manual_emails" placeholder="pessoa1@dominio.gov.br&#10;pessoa2@dominio.gov.br"></textarea>
            </label>
          </div>
          <div class="preview" id="previewBox">Nenhum destinatário carregado ainda.</div>
        </div>

        <div>
          <p class="panel-title">Mensagem</p>
          <label>
            Assunto
            <input name="subject" required placeholder="Assunto da mensagem">
          </label>
          <div class="checks">
            <label class="check"><input type="checkbox" name="is_html" id="isHtmlToggle"> Editor HTML</label>
            <label class="check"><input type="checkbox" name="send_copy_to_self" checked> Enviar cópia para mim no final</label>
          </div>
          <div id="plainEditorBox">
            <label>
              Corpo
              <textarea name="body" id="plainBody" required placeholder="Olá {{nome}},&#10;&#10;Digite aqui a mensagem da mala direta."></textarea>
            </label>
          </div>
          <div id="htmlEditorBox" class="hidden">
            <label>
              Corpo em HTML
              <div class="editor-shell">
                <div class="editor-toolbar">
                  <button type="button" class="tool-btn" data-command="bold"><strong>B</strong></button>
                  <button type="button" class="tool-btn" data-command="italic"><em>I</em></button>
                  <button type="button" class="tool-btn" data-command="underline"><u>U</u></button>
                  <button type="button" class="tool-btn" data-command="insertUnorderedList">Lista</button>
                  <button type="button" class="tool-btn" data-command="createLink">Link</button>
                  <button type="button" class="tool-btn" data-command="removeFormat">Limpar</button>
                </div>
                <div id="htmlBodyEditor" class="html-editor" contenteditable="true">Olá {{nome}},<br><br>Digite aqui a mensagem da mala direta.</div>
              </div>
            </label>
            <textarea name="body_html" id="htmlBodyValue" class="hidden"></textarea>
            <div class="hint">Use a barra para aplicar negrito, itálico, sublinhado, lista e link. As variáveis como {{nome}} continuam funcionando.</div>
          </div>
        </div>

        <div>
          <p class="panel-title">Ritmo de envio</p>
          <div class="grid">
            <label>
              Delay mínimo entre envios, em segundos
              <input type="number" name="delay_min" min="1" max="3600" value="20" required>
            </label>
            <label>
              Delay máximo entre envios, em segundos
              <input type="number" name="delay_max" min="1" max="3600" value="45" required>
            </label>
            <label>
              Pausa a cada quantos envios
              <input type="number" name="batch_size" min="0" max="500" value="25">
            </label>
            <label>
              Duração da pausa do lote, em segundos
              <input type="number" name="batch_pause" min="0" max="7200" value="300">
            </label>
            <label>
              Limite máximo por hora
              <input type="number" name="max_per_hour" min="1" max="2000" value="90" required>
            </label>
            <label>
              Responder para
              <input type="email" name="reply_to" placeholder="opcional@tceal.tc.br">
            </label>
          </div>
          <div class="hint">Use valores conservadores para contas Microsoft. O sistema aplica delay aleatório, pausa por lote e teto por hora ao mesmo tempo.</div>
        </div>

        <div class="actions">
          <button type="button" id="previewBtn">Pré-validar lista</button>
          <button type="submit" class="primary">Iniciar envio</button>
          <span class="hint">A senha fica apenas na memória enquanto o envio roda.</span>
        </div>
      </form>
    </section>

    <aside>
      <div id="statusBox" class="status">Pronto para configurar a campanha.</div>
      <div class="progress"><div id="progressBar"></div></div>
      <div class="stats">
        <div class="stat"><strong id="totalStat">0</strong><span>Total</span></div>
        <div class="stat"><strong id="sentStat">0</strong><span>Enviados</span></div>
        <div class="stat"><strong id="failStat">0</strong><span>Falhas</span></div>
        <div class="stat"><strong id="skipStat">0</strong><span>Ignorados</span></div>
      </div>
      <div class="actions">
        <button type="button" id="pauseBtn" disabled>Pausar</button>
        <button type="button" id="resumeBtn" disabled>Retomar</button>
        <button type="button" class="danger" id="cancelBtn" disabled>Cancelar</button>
      </div>
      <div class="log" id="logBox">Aguardando envio...</div>
    </aside>
  </main>

  <script>
    const form = document.querySelector("#mailForm");
    const previewBox = document.querySelector("#previewBox");
    const statusBox = document.querySelector("#statusBox");
    const logBox = document.querySelector("#logBox");
    const progressBar = document.querySelector("#progressBar");
    const totalStat = document.querySelector("#totalStat");
    const sentStat = document.querySelector("#sentStat");
    const failStat = document.querySelector("#failStat");
    const skipStat = document.querySelector("#skipStat");
    const pauseBtn = document.querySelector("#pauseBtn");
    const resumeBtn = document.querySelector("#resumeBtn");
    const cancelBtn = document.querySelector("#cancelBtn");
    const isHtmlToggle = document.querySelector("#isHtmlToggle");
    const plainEditorBox = document.querySelector("#plainEditorBox");
    const htmlEditorBox = document.querySelector("#htmlEditorBox");
    const plainBody = document.querySelector("#plainBody");
    const htmlBodyEditor = document.querySelector("#htmlBodyEditor");
    const htmlBodyValue = document.querySelector("#htmlBodyValue");
    let pollTimer = null;

    document.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
        document.querySelectorAll(".sourceBox").forEach((box) => box.classList.add("hidden"));
        tab.classList.add("active");
        document.querySelector("#" + tab.dataset.target).classList.remove("hidden");
      });
    });

    function formDataWithSource() {
      syncBodyFields();
      const data = new FormData(form);
      data.set("source", document.querySelector(".tab.active").dataset.target.replace("Box", ""));
      return data;
    }

    function syncBodyFields() {
      htmlBodyValue.value = htmlBodyEditor.innerHTML.trim();
    }

    function encodeHtml(text) {
      return String(text)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll("\n", "<br>");
    }

    function toggleEditorMode() {
      const htmlMode = isHtmlToggle.checked;
      plainEditorBox.classList.toggle("hidden", htmlMode);
      htmlEditorBox.classList.toggle("hidden", !htmlMode);
      plainBody.required = !htmlMode;
      htmlBodyValue.required = htmlMode;
      if (htmlMode && !htmlBodyEditor.innerHTML.trim()) {
        htmlBodyEditor.innerHTML = plainBody.value.trim()
          ? encodeHtml(plainBody.value)
          : "Olá {{nome}},<br><br>Digite aqui a mensagem da mala direta.";
      }
      if (!htmlMode && !plainBody.value.trim()) {
        plainBody.value = htmlBodyEditor.innerText.trim();
      }
      syncBodyFields();
    }

    isHtmlToggle.addEventListener("change", toggleEditorMode);
    htmlBodyEditor.addEventListener("input", syncBodyFields);

    document.querySelectorAll(".tool-btn").forEach((button) => {
      button.addEventListener("click", () => {
        htmlBodyEditor.focus();
        if (button.dataset.command === "createLink") {
          const link = window.prompt("Informe a URL do link:");
          if (link) document.execCommand("createLink", false, link);
        } else {
          document.execCommand(button.dataset.command, false, null);
        }
        syncBodyFields();
      });
    });

    async function post(path, data) {
      const response = await fetch(path, { method: "POST", body: data });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Não foi possível concluir a ação.");
      return payload;
    }

    document.querySelector("#previewBtn").addEventListener("click", async () => {
      previewBox.textContent = "Validando lista...";
      try {
        const payload = await post("/api/preview", formDataWithSource());
        previewBox.innerHTML = `<strong>${payload.valid}</strong> e-mails válidos, <strong>${payload.invalid}</strong> inválidos/duplicados. Amostra: ${payload.sample.map(escapeHtml).join(", ") || "sem amostra"}.`;
      } catch (error) {
        previewBox.textContent = error.message;
      }
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      statusBox.className = "status";
      statusBox.textContent = "Preparando campanha...";
      try {
        const payload = await post("/api/start", formDataWithSource());
        if (payload.job) renderJob(payload.job);
        startPolling();
      } catch (error) {
        statusBox.className = "status error";
        statusBox.textContent = error.message;
      }
    });

    pauseBtn.addEventListener("click", () => fetch("/api/pause", { method: "POST" }).then(updateStatus));
    resumeBtn.addEventListener("click", () => fetch("/api/resume", { method: "POST" }).then(updateStatus));
    cancelBtn.addEventListener("click", () => fetch("/api/cancel", { method: "POST" }).then(updateStatus));

    function startPolling() {
      clearInterval(pollTimer);
      updateStatus();
      pollTimer = setInterval(updateStatus, 1500);
    }

    async function updateStatus() {
      try {
        const response = await fetch("/api/status");
        const job = await response.json();
        renderJob(job);
      } catch (error) {
        statusBox.className = "status error";
        statusBox.textContent = "Não foi possível atualizar o andamento da campanha.";
      }
    }

    function renderJob(job) {
      totalStat.textContent = job.total || 0;
      sentStat.textContent = job.sent || 0;
      failStat.textContent = job.failed || 0;
      skipStat.textContent = job.skipped || 0;
      const done = (job.sent || 0) + (job.failed || 0) + (job.skipped || 0);
      const pct = job.total ? Math.round(done * 100 / job.total) : 0;
      progressBar.style.width = pct + "%";
      const active = ["running", "paused"].includes(job.status);
      pauseBtn.disabled = job.status !== "running";
      resumeBtn.disabled = job.status !== "paused";
      cancelBtn.disabled = !active;
      statusBox.className = "status";
      if (job.status === "done") statusBox.classList.add("done");
      if (job.status === "failed" || job.status === "cancelled") statusBox.classList.add("error");
      if (job.status === "paused") statusBox.classList.add("paused");
      statusBox.textContent = statusText(job);
      logBox.innerHTML = (job.logs || []).map((entry) => {
        return `<div>[${escapeHtml(entry.time)}] ${escapeHtml(entry.message)}</div>`;
      }).join("") || "Aguardando envio...";
      logBox.scrollTop = logBox.scrollHeight;
      if (["done", "failed", "cancelled"].includes(job.status)) clearInterval(pollTimer);
    }

    function statusText(job) {
      if (!job.id) return "Pronto para configurar a campanha.";
      if (job.status === "paused") return "Envio pausado. A fila será retomada quando você clicar em Retomar.";
      if (job.status === "done") return "Campanha concluída.";
      if (job.status === "cancelled") return "Campanha cancelada.";
      if (job.status === "failed") return "A campanha foi interrompida por falha.";
      if (job.next_send_in && job.next_send_in > 0) return `Enviando com controle de ritmo. Próximo envio em ${job.next_send_in}s.`;
      return job.current ? `Processando ${job.current}` : "Envio em andamento.";
    }

    function escapeHtml(text) {
      return String(text).replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#039;"
      }[char]));
    }

    toggleEditorMode();
    updateStatus();
  </script>
</body>
</html>
"""


def now_text() -> str:
    return time.strftime("%H:%M:%S")


def add_log(job: MailJob, message: str) -> None:
    with JOB_LOCK:
        job.logs.append({"time": now_text(), "message": message})
        job.logs = job.logs[-300:]


def sanitize_html(raw_html: str) -> str:
    cleaned = re.sub(r"<script\b[^>]*>.*?</script>", "", raw_html or "", flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"\son\w+\s*=\s*(\".*?\"|'.*?'|[^\s>]+)", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def parse_multipart_form(raw_body: bytes, content_type: str) -> FormData:
    message = BytesParser(policy=policy.default).parsebytes(
        b"MIME-Version: 1.0\r\n"
        + f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
        + raw_body
    )
    form = FormData()
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            form.files[name] = FormFile(filename=filename, value=payload)
            continue
        charset = part.get_content_charset() or "utf-8"
        value = payload.decode(charset, errors="replace")
        form.fields.setdefault(name, []).append(value)
    return form


def parse_bool(value: Any) -> bool:
    return str(value or "").lower() in {"1", "true", "on", "yes", "sim"}


def clean_username(username: str) -> str:
    username = (username or "").strip()
    if username.endswith(EMAIL_DOMAIN):
        username = username[: -len(EMAIL_DOMAIN)]
    username = username.replace("@", "").strip()
    if not username:
        raise ValueError("Informe o usuário do e-mail.")
    return f"{username}{EMAIL_DOMAIN}"


def as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def extract_emails(text: str) -> list[Recipient]:
    items = re.split(r"[\s,;]+", text or "")
    return [Recipient(email=item.strip()) for item in items if item.strip()]


def parse_csv_recipients(raw: bytes) -> list[Recipient]:
    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;|\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        return extract_emails(text)

    normalized = {name.lower().strip(): name for name in reader.fieldnames if name}
    email_field = normalized.get("email") or normalized.get("e-mail") or normalized.get("mail")
    if not email_field:
        email_field = reader.fieldnames[0]

    recipients: list[Recipient] = []
    for row in reader:
        email_value = (row.get(email_field) or "").strip()
        fields = {str(key).strip(): str(value or "").strip() for key, value in row.items() if key}
        recipients.append(Recipient(email=email_value, fields=fields))
    return recipients


def parse_recipients(fields: FormData) -> tuple[list[Recipient], int]:
    source = field_value(fields, "source", "csv")
    recipients: list[Recipient] = []

    if source == "csv":
        file_item = fields.files.get("csv_file")
        if file_item is None or not file_item.filename:
            raise ValueError("Selecione um arquivo CSV.")
        recipients = parse_csv_recipients(file_item.value)
    elif source == "txt":
        file_item = fields.files.get("txt_file")
        if file_item is None or not file_item.filename:
            raise ValueError("Selecione um arquivo TXT.")
        recipients = extract_emails(file_item.value.decode("utf-8-sig", errors="replace"))
    else:
        recipients = extract_emails(field_value(fields, "manual_emails", ""))

    seen: set[str] = set()
    valid: list[Recipient] = []
    invalid = 0
    for recipient in recipients:
        email_address = (recipient.email or "").strip().lower()
        if not EMAIL_RE.match(email_address) or email_address in seen:
            invalid += 1
            continue
        seen.add(email_address)
        recipient.email = email_address
        recipient.fields.setdefault("email", email_address)
        valid.append(recipient)
    return valid, invalid


def field_value(fields: FormData, name: str, default: str = "") -> str:
    values = fields.fields.get(name)
    if not values:
        return default
    return str(values[0] if values[0] is not None else default)


def render_template(text: str, recipient: Recipient, sender: str) -> str:
    values = {"email": recipient.email, "sender": sender, **recipient.fields}

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(values.get(key, ""))

    return TOKEN_RE.sub(replace, text)


def build_message(
    sender: str,
    recipient: Recipient,
    subject: str,
    body: str,
    is_html: bool,
    reply_to: str,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient.email
    if reply_to:
        message["Reply-To"] = reply_to
    message["Subject"] = render_template(subject, recipient, sender)
    rendered_body = render_template(body, recipient, sender)
    if is_html:
        message.set_content("Esta mensagem possui conteudo em HTML.")
        message.add_alternative(rendered_body, subtype="html")
    else:
        message.set_content(rendered_body)
    return message


def sleep_interruptibly(job: MailJob, seconds: int) -> bool:
    target = time.time() + max(0, seconds)
    with JOB_LOCK:
        job.next_send_at = target if seconds > 0 else None
    while time.time() < target:
        if job.cancel_event.is_set():
            return False
        while job.pause_event.is_set():
            with JOB_LOCK:
                job.status = "paused"
                job.next_send_at = None
            if job.cancel_event.wait(0.5):
                return False
        with JOB_LOCK:
            if job.status == "paused":
                job.status = "running"
        time.sleep(min(0.5, target - time.time()))
    with JOB_LOCK:
        job.next_send_at = None
    return True


def enforce_hourly_limit(job: MailJob, sent_times: list[float], max_per_hour: int) -> bool:
    now = time.time()
    sent_times[:] = [item for item in sent_times if now - item < 3600]
    if len(sent_times) < max_per_hour:
        return True
    wait_for = int(3600 - (now - sent_times[0])) + 1
    add_log(job, f"Limite por hora atingido. Aguardando {wait_for}s antes de continuar.")
    return sleep_interruptibly(job, wait_for)


def run_job(
    job: MailJob,
    password: str,
    recipients: list[Recipient],
    body: str,
    is_html: bool,
    reply_to: str,
    delay_min: int,
    delay_max: int,
    batch_size: int,
    batch_pause: int,
    max_per_hour: int,
    send_copy_to_self: bool,
) -> None:
    sent_times: list[float] = []
    context = ssl.create_default_context()
    add_log(job, f"Conectando ao servidor {SMTP_SERVER}:{SMTP_PORT}.")
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=45) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(job.sender, password)
            add_log(job, f"Autenticado como {job.sender}. Iniciando fila com {job.total} destinatários.")

            for index, recipient in enumerate(recipients, start=1):
                if job.cancel_event.is_set():
                    break
                while job.pause_event.is_set():
                    with JOB_LOCK:
                        job.status = "paused"
                    if job.cancel_event.wait(0.5):
                        break
                with JOB_LOCK:
                    job.status = "running"
                    job.current = recipient.email

                if not enforce_hourly_limit(job, sent_times, max_per_hour):
                    break

                try:
                    message = build_message(job.sender, recipient, job.subject, body, is_html, reply_to)
                    smtp.send_message(message)
                    sent_times.append(time.time())
                    with JOB_LOCK:
                        job.sent += 1
                    add_log(job, f"Enviado para {recipient.email} ({index}/{job.total}).")
                except Exception as exc:  # noqa: BLE001
                    with JOB_LOCK:
                        job.failed += 1
                    add_log(job, f"Falha ao enviar para {recipient.email}: {exc}")

                if index < len(recipients):
                    if batch_size and index % batch_size == 0 and batch_pause:
                        add_log(job, f"Pausa de lote após {index} envios por {batch_pause}s.")
                        if not sleep_interruptibly(job, batch_pause):
                            break
                    else:
                        delay = random.randint(delay_min, delay_max)
                        if not sleep_interruptibly(job, delay):
                            break

            if send_copy_to_self and not job.cancel_event.is_set():
                copy_recipient = Recipient(email=job.sender, fields={"nome": "Remetente", "email": job.sender})
                copy_message = build_message(job.sender, copy_recipient, f"[Cópia] {job.subject}", body, is_html, reply_to)
                smtp.send_message(copy_message)
                add_log(job, "Cópia final enviada para a conta remetente.")

        with JOB_LOCK:
            job.current = ""
            job.finished_at = time.time()
            job.status = "cancelled" if job.cancel_event.is_set() else "done"
        add_log(job, "Campanha cancelada." if job.cancel_event.is_set() else "Campanha concluída.")
    except Exception as exc:  # noqa: BLE001
        with JOB_LOCK:
            job.current = ""
            job.finished_at = time.time()
            job.status = "failed"
        add_log(job, f"Envio interrompido: {exc}")


def job_snapshot() -> dict[str, Any]:
    with JOB_LOCK:
        job = CURRENT_JOB
        if not job:
            return {"id": None, "status": "idle", "logs": []}
        next_send_in = 0
        if job.next_send_at:
            next_send_in = max(0, int(job.next_send_at - time.time()))
        return {
            "id": job.id,
            "sender": job.sender,
            "subject": job.subject,
            "status": job.status,
            "total": job.total,
            "sent": job.sent,
            "failed": job.failed,
            "skipped": job.skipped,
            "current": job.current,
            "next_send_in": next_send_in,
            "logs": list(job.logs),
        }


class MailerHandler(BaseHTTPRequestHandler):
    server_version = "MalaDiretaTCE/1.0"

    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            self.send_text(INDEX_HTML, "text/html; charset=utf-8")
            return
        if self.path == "/api/status":
            self.send_json(job_snapshot())
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            if self.path == "/api/preview":
                self.handle_preview()
            elif self.path == "/api/start":
                self.handle_start()
            elif self.path == "/api/pause":
                self.handle_pause()
            elif self.path == "/api/resume":
                self.handle_resume()
            elif self.path == "/api/cancel":
                self.handle_cancel()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": f"Erro inesperado: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_preview(self) -> None:
        fields = self.read_form()
        recipients, invalid = parse_recipients(fields)
        self.send_json(
            {
                "valid": len(recipients),
                "invalid": invalid,
                "sample": [recipient.email for recipient in recipients[:8]],
            }
        )

    def handle_start(self) -> None:
        global CURRENT_JOB

        with JOB_LOCK:
            if CURRENT_JOB and CURRENT_JOB.status in {"running", "paused"}:
                raise ValueError("Já existe uma campanha em andamento. Pause, cancele ou aguarde terminar.")

        fields = self.read_form()
        sender = clean_username(field_value(fields, "username"))
        password = field_value(fields, "password")
        if not password:
            raise ValueError("Informe a senha do e-mail.")
        recipients, invalid = parse_recipients(fields)
        if not recipients:
            raise ValueError("Nenhum e-mail válido foi encontrado.")

        subject = field_value(fields, "subject").strip()
        is_html = parse_bool(field_value(fields, "is_html"))
        body = field_value(fields, "body_html" if is_html else "body").strip()
        if is_html:
            body = sanitize_html(body)
        if not subject or not body:
            raise ValueError("Informe assunto e corpo da mensagem.")

        delay_min = as_int(field_value(fields, "delay_min"), 20, 1, 3600)
        delay_max = as_int(field_value(fields, "delay_max"), 45, 1, 3600)
        if delay_min > delay_max:
            delay_min, delay_max = delay_max, delay_min
        batch_size = as_int(field_value(fields, "batch_size"), 25, 0, 500)
        batch_pause = as_int(field_value(fields, "batch_pause"), 300, 0, 7200)
        max_per_hour = as_int(field_value(fields, "max_per_hour"), 90, 1, 2000)
        reply_to = field_value(fields, "reply_to").strip()
        if reply_to and not EMAIL_RE.match(reply_to):
            raise ValueError("O campo Responder para precisa ser um e-mail válido.")

        job = MailJob(
            id=str(uuid.uuid4()),
            sender=sender,
            total=len(recipients),
            subject=subject,
            skipped=invalid,
        )
        with JOB_LOCK:
            CURRENT_JOB = job
        add_log(job, "Campanha criada. Preparando autenticação e fila de envio.")
        if invalid:
            add_log(job, f"{invalid} item(ns) inválido(s) ou duplicado(s) foram ignorados.")

        thread = threading.Thread(
            target=run_job,
            args=(
                job,
                password,
                recipients,
                body,
                is_html,
                reply_to,
                delay_min,
                delay_max,
                batch_size,
                batch_pause,
                max_per_hour,
                parse_bool(field_value(fields, "send_copy_to_self")),
            ),
            daemon=True,
        )
        thread.start()
        self.send_json({"ok": True, "job_id": job.id, "job": job_snapshot()})

    def handle_pause(self) -> None:
        should_log = False
        with JOB_LOCK:
            job = CURRENT_JOB
            if job and job.status == "running":
                job.pause_event.set()
                job.status = "paused"
                job.next_send_at = None
                should_log = True
        if should_log and job:
            add_log(job, "Pausa solicitada pelo usuário.")
        self.send_json(job_snapshot())

    def handle_resume(self) -> None:
        should_log = False
        with JOB_LOCK:
            job = CURRENT_JOB
            if job and job.status == "paused":
                job.pause_event.clear()
                job.status = "running"
                should_log = True
        if should_log and job:
            add_log(job, "Envio retomado pelo usuário.")
        self.send_json(job_snapshot())

    def handle_cancel(self) -> None:
        should_log = False
        with JOB_LOCK:
            job = CURRENT_JOB
            if job and job.status in {"running", "paused"}:
                job.cancel_event.set()
                job.pause_event.clear()
                job.status = "cancelled"
                job.next_send_at = None
                should_log = True
        if should_log and job:
            add_log(job, "Cancelamento solicitado pelo usuário.")
        self.send_json(job_snapshot())

    def read_form(self) -> FormData:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("Envie os dados do formulário corretamente.")
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        return parse_multipart_form(raw_body, content_type)

    def send_text(self, content: str, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    httpd = ThreadingHTTPServer((APP_HOST, APP_PORT), MailerHandler)
    print(f"Mala Direta TCE/AL aberta em http://{APP_HOST}:{APP_PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
