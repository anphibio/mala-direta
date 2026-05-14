from __future__ import annotations

import csv
import html
import io
import json
import os
import random
import re
import smtplib
import sqlite3
import ssl
import threading
import time
import uuid
import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


SMTP_SERVER = "smtp.tceal.tc.br"
SMTP_PORT = 587
EMAIL_DOMAIN = "@tceal.tc.br"
APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8086"))
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = DATA_DIR / "reports"
DB_PATH = DATA_DIR / "mala_direta.db"
KEY_PATH = DATA_DIR / "app.key"
LEGACY_HISTORY_FILE = DATA_DIR / "campaign_history.json"
LEGACY_SUPPRESSION_FILE = DATA_DIR / "suppression_list.json"
MICROSOFT_DOMAINS = {
    "hotmail.com",
    "hotmail.com.br",
    "outlook.com",
    "outlook.com.br",
    "live.com",
    "msn.com",
    "office365.com",
    "onmicrosoft.com",
}

DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")
BRAND_IMAGE_URL = "https://www.tceal.tc.br/view/img/logo_main.png"


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
    scheduled_for: float | None = None
    report_path: str | None = None
    logs: list[dict[str, Any]] = field(default_factory=list)
    report_rows: list[dict[str, str]] = field(default_factory=list)
    pause_event: threading.Event = field(default_factory=threading.Event)
    cancel_event: threading.Event = field(default_factory=threading.Event)


JOB_LOCK = threading.Lock()
CURRENT_JOB: MailJob | None = None
DB_LOCK = threading.Lock()


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
      background:
        radial-gradient(circle at top left, rgba(32, 84, 147, .10), transparent 28%),
        linear-gradient(180deg, #fbfcfe 0%, #f3f6fa 100%);
      color: var(--ink);
    }
    header {
      background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(255,255,255,.92));
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      z-index: 5;
      backdrop-filter: blur(8px);
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
    .brand {
      display: flex;
      align-items: center;
      gap: 16px;
      min-width: 0;
    }
    .brand img {
      width: 240px;
      max-width: min(42vw, 240px);
      height: auto;
      display: block;
      flex: 0 0 auto;
    }
    .brand-copy {
      min-width: 0;
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
      position: relative;
      overflow: hidden;
    }
    section:before, aside:before {
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(135deg, rgba(32, 84, 147, .05), transparent 42%),
        linear-gradient(315deg, rgba(159, 45, 32, .05), transparent 36%);
      pointer-events: none;
    }
    .form {
      padding: 22px;
      display: grid;
      gap: 18px;
      position: relative;
      z-index: 1;
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
      background-image: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.98));
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
      .brand { flex-direction: column; align-items: flex-start; }
      .brand img { max-width: min(72vw, 240px); }
      .server { white-space: normal; }
      .grid { grid-template-columns: 1fr; }
      .form { padding: 16px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <div class="brand">
        <img src="__BRAND_IMAGE_URL__" alt="TCE-AL">
        <div class="brand-copy">
        <h1>Mala Direta TCE/AL</h1>
        <div class="hint">Envio autenticado com controles de ritmo, fila e personalização por CSV.</div>
        </div>
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
            <label>
              Agendar para
              <input type="datetime-local" name="schedule_at">
            </label>
          </div>
          <div class="hint">Use valores conservadores para contas Microsoft. O sistema aplica delay aleatório, pausa por lote, teto por hora e espaçamento extra automático para domínios Microsoft.</div>
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
        <button type="button" id="reportBtn" disabled>Baixar relatório</button>
      </div>
      <div class="log" id="logBox">Aguardando envio...</div>
      <div>
        <p class="panel-title">Histórico recente</p>
        <div class="hint" id="suppressionInfo">Lista de supressão: 0 contato(s).</div>
        <div class="preview" id="activeCampaignsBox">Nenhuma campanha em andamento.</div>
        <div class="preview" id="historyBox">Nenhuma campanha registrada ainda.</div>
      </div>
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
    const reportBtn = document.querySelector("#reportBtn");
    const historyBox = document.querySelector("#historyBox");
    const suppressionInfo = document.querySelector("#suppressionInfo");
    const activeCampaignsBox = document.querySelector("#activeCampaignsBox");
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
    reportBtn.addEventListener("click", () => {
      if (reportBtn.dataset.url) window.open(reportBtn.dataset.url, "_blank");
    });

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
        updateHistory();
      } catch (error) {
        statusBox.className = "status error";
        statusBox.textContent = "Não foi possível atualizar o andamento da campanha.";
      }
    }

    async function updateHistory() {
      try {
        const response = await fetch("/api/history");
        const payload = await response.json();
        suppressionInfo.textContent = `Lista de supressão: ${payload.suppression_count || 0} contato(s).`;
        activeCampaignsBox.innerHTML = (payload.active_items || []).length
          ? payload.active_items.map((item) => {
              const when = item.scheduled_for_text || item.created_at_text || "";
              return `<div style="padding:8px 0;border-bottom:1px solid #e5e7eb;"><strong>${escapeHtml(item.subject)}</strong><br>${escapeHtml(item.status)} | ${item.sent}/${item.total} enviados | ${escapeHtml(when)}<br><button type="button" class="tool-btn active-cancel-btn" data-id="${escapeHtml(item.id)}">Cancelar campanha</button></div>`;
            }).join("")
          : "Nenhuma campanha em andamento.";
        historyBox.innerHTML = (payload.items || []).length
          ? payload.items.map((item) => {
              const when = item.scheduled_for_text || item.created_at_text || "";
              const footer = item.report_url ? `<a href="${item.report_url}" target="_blank">Relatório</a>` : "";
              return `<div style="padding:8px 0;border-bottom:1px solid #e5e7eb;"><strong>${escapeHtml(item.subject)}</strong><br>${escapeHtml(item.status)} | ${item.sent}/${item.total} enviados | ${escapeHtml(when)} ${footer}</div>`;
            }).join("")
          : "Nenhuma campanha registrada ainda.";
        document.querySelectorAll(".active-cancel-btn").forEach((button) => {
          button.addEventListener("click", async () => {
            button.disabled = true;
            try {
              await fetch(`/api/cancel?id=${encodeURIComponent(button.dataset.id)}`, { method: "POST" });
              updateStatus();
            } catch (error) {
              button.disabled = false;
            }
          });
        });
      } catch (error) {
        historyBox.textContent = "Não foi possível carregar o histórico.";
        activeCampaignsBox.textContent = "Não foi possível carregar as campanhas em andamento.";
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
      cancelBtn.disabled = !["running", "paused", "scheduled"].includes(job.status);
      reportBtn.disabled = !job.report_url;
      reportBtn.dataset.url = job.report_url || "";
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
      if (job.status === "scheduled") return `Campanha agendada para ${job.scheduled_for_text || "horário informado"}.`;
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
    updateHistory();
  </script>
</body>
</html>
"""
INDEX_HTML = INDEX_HTML.replace("__BRAND_IMAGE_URL__", BRAND_IMAGE_URL)


def now_text() -> str:
    return time.strftime("%H:%M:%S")


def format_timestamp(timestamp: float | None) -> str:
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y %H:%M")


def read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def db_connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def get_master_key() -> bytes:
    env_key = os.getenv("APP_MASTER_KEY", "").strip()
    if env_key:
        return hashlib.sha256(env_key.encode("utf-8")).digest()
    if not KEY_PATH.exists():
        KEY_PATH.write_bytes(base64.urlsafe_b64encode(secrets.token_bytes(32)))
        try:
            os.chmod(KEY_PATH, 0o600)
        except OSError:
            pass
    return hashlib.sha256(KEY_PATH.read_bytes()).digest()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < length:
        block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        output.extend(block)
        counter += 1
    return bytes(output[:length])


def encrypt_secret(secret_text: str) -> str:
    plaintext = secret_text.encode("utf-8")
    key = get_master_key()
    nonce = secrets.token_bytes(16)
    cipher = bytes(a ^ b for a, b in zip(plaintext, _keystream(key, nonce, len(plaintext))))
    mac = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + mac + cipher).decode("ascii")


def decrypt_secret(token: str) -> str:
    blob = base64.urlsafe_b64decode(token.encode("ascii"))
    nonce = blob[:16]
    mac = blob[16:48]
    cipher = blob[48:]
    key = get_master_key()
    expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("Não foi possível validar a credencial armazenada.")
    plain = bytes(a ^ b for a, b in zip(cipher, _keystream(key, nonce, len(cipher))))
    return plain.decode("utf-8")


def init_database() -> None:
    with DB_LOCK, db_connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                sender TEXT NOT NULL,
                subject TEXT NOT NULL,
                status TEXT NOT NULL,
                total INTEGER NOT NULL,
                sent INTEGER NOT NULL,
                failed INTEGER NOT NULL,
                skipped INTEGER NOT NULL,
                created_at REAL NOT NULL,
                scheduled_for REAL,
                finished_at REAL,
                report_path TEXT,
                payload_json TEXT,
                encrypted_password TEXT
            );

            CREATE TABLE IF NOT EXISTS suppression_list (
                email TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(campaigns)").fetchall()
        }
        if "payload_json" not in existing_columns:
            connection.execute("ALTER TABLE campaigns ADD COLUMN payload_json TEXT")
        if "encrypted_password" not in existing_columns:
            connection.execute("ALTER TABLE campaigns ADD COLUMN encrypted_password TEXT")
        connection.commit()
    migrate_legacy_storage()


def migrate_legacy_storage() -> None:
    legacy_history = read_json_file(LEGACY_HISTORY_FILE, [])
    legacy_suppression = read_json_file(LEGACY_SUPPRESSION_FILE, {})
    if not legacy_history and not legacy_suppression:
        return
    with DB_LOCK, db_connect() as connection:
        for item in legacy_history:
            connection.execute(
                """
                INSERT OR REPLACE INTO campaigns
                (id, sender, subject, status, total, sent, failed, skipped, created_at, scheduled_for, finished_at, report_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.get("id", str(uuid.uuid4())),
                    item.get("sender", ""),
                    item.get("subject", ""),
                    item.get("status", "done"),
                    int(item.get("total", 0)),
                    int(item.get("sent", 0)),
                    int(item.get("failed", 0)),
                    int(item.get("skipped", 0)),
                    float(item.get("created_at", time.time())),
                    item.get("scheduled_for"),
                    item.get("finished_at"),
                    (item.get("report_url", "").split("id=")[-1] + ".csv") if item.get("report_url") else "",
                ),
            )
        for email_address, payload in legacy_suppression.items():
            connection.execute(
                "INSERT OR REPLACE INTO suppression_list (email, reason, created_at) VALUES (?, ?, ?)",
                (
                    email_address.lower(),
                    payload.get("reason", "Lista migrada"),
                    payload.get("created_at", format_timestamp(time.time())),
                ),
            )
        connection.commit()
    if LEGACY_HISTORY_FILE.exists():
        LEGACY_HISTORY_FILE.unlink()
    if LEGACY_SUPPRESSION_FILE.exists():
        LEGACY_SUPPRESSION_FILE.unlink()


def load_history() -> list[dict[str, Any]]:
    with DB_LOCK, db_connect() as connection:
        rows = connection.execute(
            """
            SELECT id, sender, subject, status, total, sent, failed, skipped, created_at, scheduled_for, finished_at, report_path
            FROM campaigns
            ORDER BY created_at DESC
            LIMIT 50
            """
        ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        report_path = row["report_path"] or ""
        items.append(
            {
                "id": row["id"],
                "sender": row["sender"],
                "subject": row["subject"],
                "status": row["status"],
                "total": row["total"],
                "sent": row["sent"],
                "failed": row["failed"],
                "skipped": row["skipped"],
                "created_at": row["created_at"],
                "created_at_text": format_timestamp(row["created_at"]),
                "scheduled_for": row["scheduled_for"],
                "scheduled_for_text": format_timestamp(row["scheduled_for"]),
                "finished_at": row["finished_at"],
                "finished_at_text": format_timestamp(row["finished_at"]),
                "report_url": f"/api/report?id={row['id']}" if report_path else "",
            }
        )
    return items


def load_active_campaigns() -> list[dict[str, Any]]:
    return [item for item in load_history() if item.get("status") in {"running", "paused", "scheduled"}]


def load_suppression_list() -> dict[str, dict[str, str]]:
    with DB_LOCK, db_connect() as connection:
        rows = connection.execute("SELECT email, reason, created_at FROM suppression_list").fetchall()
    return {
        row["email"]: {
            "reason": row["reason"],
            "created_at": row["created_at"],
        }
        for row in rows
    }


def recipient_domain(email_address: str) -> str:
    return email_address.rsplit("@", 1)[-1].lower()


def has_active_campaign() -> bool:
    with DB_LOCK, db_connect() as connection:
        row = connection.execute(
            "SELECT id FROM campaigns WHERE status IN ('running', 'paused', 'scheduled') ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return row is not None


def cancel_campaign_by_id(campaign_id: str) -> bool:
    global CURRENT_JOB
    if not campaign_id:
        return False
    cancelled = False
    with JOB_LOCK:
        if CURRENT_JOB and CURRENT_JOB.id == campaign_id and CURRENT_JOB.status in {"running", "paused", "scheduled"}:
            CURRENT_JOB.cancel_event.set()
            CURRENT_JOB.pause_event.clear()
            CURRENT_JOB.status = "cancelled"
            CURRENT_JOB.next_send_at = None
            CURRENT_JOB.finished_at = time.time()
            add_log(CURRENT_JOB, "Cancelamento solicitado pelo usuário.")
            persist_campaign(CURRENT_JOB)
            cancelled = True
    if cancelled:
        return True
    with DB_LOCK, db_connect() as connection:
        row = connection.execute(
            "SELECT id, status FROM campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if not row or row["status"] not in {"running", "paused", "scheduled"}:
            return False
        connection.execute(
            """
            UPDATE campaigns
            SET status = 'cancelled', finished_at = ?, payload_json = NULL, encrypted_password = NULL
            WHERE id = ?
            """,
            (time.time(), campaign_id),
        )
        connection.commit()
    return True


def persist_scheduled_payload(
    job_id: str,
    payload: dict[str, Any],
    password: str,
) -> None:
    with DB_LOCK, db_connect() as connection:
        connection.execute(
            """
            UPDATE campaigns
            SET payload_json = ?, encrypted_password = ?
            WHERE id = ?
            """,
            (json.dumps(payload, ensure_ascii=False), encrypt_secret(password), job_id),
        )
        connection.commit()


def clear_scheduled_payload(job_id: str) -> None:
    with DB_LOCK, db_connect() as connection:
        connection.execute(
            "UPDATE campaigns SET payload_json = NULL, encrypted_password = NULL WHERE id = ?",
            (job_id,),
        )
        connection.commit()


def load_pending_scheduled_campaign() -> dict[str, Any] | None:
    with DB_LOCK, db_connect() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM campaigns
            WHERE status = 'scheduled' AND payload_json IS NOT NULL AND encrypted_password IS NOT NULL
            ORDER BY scheduled_for ASC, created_at ASC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def save_report(job: MailJob) -> None:
    report_path = REPORTS_DIR / f"{job.id}.csv"
    with report_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp", "email", "domain", "status", "detail"],
        )
        writer.writeheader()
        writer.writerows(job.report_rows)
    job.report_path = report_path.name


def campaign_summary(job: MailJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "sender": job.sender,
        "subject": job.subject,
        "status": job.status,
        "total": job.total,
        "sent": job.sent,
        "failed": job.failed,
        "skipped": job.skipped,
        "created_at": job.created_at,
        "created_at_text": format_timestamp(job.created_at),
        "scheduled_for": job.scheduled_for,
        "scheduled_for_text": format_timestamp(job.scheduled_for),
        "finished_at": job.finished_at,
        "finished_at_text": format_timestamp(job.finished_at),
        "report_url": f"/api/report?id={job.id}" if job.report_path else "",
    }


def persist_campaign(job: MailJob) -> None:
    with DB_LOCK, db_connect() as connection:
        connection.execute(
            """
            INSERT INTO campaigns
            (id, sender, subject, status, total, sent, failed, skipped, created_at, scheduled_for, finished_at, report_path, payload_json, encrypted_password)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT payload_json FROM campaigns WHERE id = ?), NULL), COALESCE((SELECT encrypted_password FROM campaigns WHERE id = ?), NULL))
            ON CONFLICT(id) DO UPDATE SET
                sender=excluded.sender,
                subject=excluded.subject,
                status=excluded.status,
                total=excluded.total,
                sent=excluded.sent,
                failed=excluded.failed,
                skipped=excluded.skipped,
                created_at=excluded.created_at,
                scheduled_for=excluded.scheduled_for,
                finished_at=excluded.finished_at,
                report_path=excluded.report_path
            """,
            (
                job.id,
                job.sender,
                job.subject,
                job.status,
                job.total,
                job.sent,
                job.failed,
                job.skipped,
                job.created_at,
                job.scheduled_for,
                job.finished_at,
                job.report_path or "",
                job.id,
                job.id,
            ),
        )
        connection.commit()


def add_suppression(email_address: str, reason: str) -> None:
    with DB_LOCK, db_connect() as connection:
        connection.execute(
            """
            INSERT INTO suppression_list (email, reason, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                reason=excluded.reason,
                created_at=excluded.created_at
            """,
            (
                email_address.lower(),
                reason,
                format_timestamp(time.time()),
            ),
        )
        connection.commit()


def suppression_count() -> int:
    return len(load_suppression_list())


def is_permanent_smtp_error(exc: Exception) -> tuple[bool, str]:
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        for _, payload in exc.recipients.items():
            if isinstance(payload, tuple) and payload:
                code = int(payload[0])
                if 500 <= code < 600:
                    detail = payload[1].decode("utf-8", errors="replace") if isinstance(payload[1], bytes) else str(payload[1])
                    return True, f"{code} {detail}".strip()
    message = str(exc).lower()
    permanent_hints = ["user unknown", "invalid recipient", "mailbox unavailable", "recipient address rejected", "not found"]
    if any(hint in message for hint in permanent_hints):
        return True, str(exc)
    return False, str(exc)


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


def parse_schedule(value: str) -> float | None:
    raw_value = (value or "").strip()
    if not raw_value:
        return None
    try:
        return datetime.strptime(raw_value, "%Y-%m-%dT%H:%M").timestamp()
    except ValueError as exc:
        raise ValueError("A data de agendamento está inválida.") from exc


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


def enforce_domain_spacing(job: MailJob, email_address: str, domain_times: dict[str, float]) -> bool:
    domain = recipient_domain(email_address)
    minimum_gap = 60 if domain in MICROSOFT_DOMAINS else 0
    if not minimum_gap:
        return True
    last_time = domain_times.get(domain)
    if last_time is None:
        return True
    remaining = int(minimum_gap - (time.time() - last_time))
    if remaining <= 0:
        return True
    add_log(job, f"Domínio {domain} em modo conservador. Aguardando {remaining}s antes do próximo envio.")
    return sleep_interruptibly(job, remaining)


def record_report_row(job: MailJob, email_address: str, status: str, detail: str) -> None:
    job.report_rows.append(
        {
            "timestamp": format_timestamp(time.time()),
            "email": email_address,
            "domain": recipient_domain(email_address),
            "status": status,
            "detail": detail,
        }
    )


def build_scheduled_payload(
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
) -> dict[str, Any]:
    return {
        "recipients": [{"email": item.email, "fields": item.fields} for item in recipients],
        "body": body,
        "is_html": is_html,
        "reply_to": reply_to,
        "delay_min": delay_min,
        "delay_max": delay_max,
        "batch_size": batch_size,
        "batch_pause": batch_pause,
        "max_per_hour": max_per_hour,
        "send_copy_to_self": send_copy_to_self,
    }


def restore_scheduled_campaigns() -> None:
    global CURRENT_JOB
    pending = load_pending_scheduled_campaign()
    if not pending:
        return
    payload = json.loads(pending["payload_json"])
    job = MailJob(
        id=pending["id"],
        sender=pending["sender"],
        total=int(pending["total"]),
        subject=pending["subject"],
        status="scheduled",
        sent=int(pending["sent"]),
        failed=int(pending["failed"]),
        skipped=int(pending["skipped"]),
        created_at=float(pending["created_at"]),
        started_at=float(pending["created_at"]),
        finished_at=pending["finished_at"],
        scheduled_for=pending["scheduled_for"],
        report_path=pending["report_path"] or None,
    )
    with JOB_LOCK:
        CURRENT_JOB = job
    add_log(job, "Campanha agendada recuperada do banco após reinício da aplicação.")
    persist_campaign(job)
    recipients = [
        Recipient(email=item["email"], fields=item.get("fields", {}))
        for item in payload.get("recipients", [])
    ]
    password = decrypt_secret(pending["encrypted_password"])
    thread = threading.Thread(
        target=run_scheduled_job,
        args=(
            job,
            password,
            recipients,
            payload.get("body", ""),
            bool(payload.get("is_html")),
            payload.get("reply_to", ""),
            int(payload.get("delay_min", 20)),
            int(payload.get("delay_max", 45)),
            int(payload.get("batch_size", 25)),
            int(payload.get("batch_pause", 300)),
            int(payload.get("max_per_hour", 90)),
            bool(payload.get("send_copy_to_self", True)),
        ),
        daemon=True,
    )
    thread.start()


def finish_job(job: MailJob) -> None:
    save_report(job)
    clear_scheduled_payload(job.id)
    persist_campaign(job)


def run_scheduled_job(
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
    if job.scheduled_for:
        wait_seconds = int(max(0, job.scheduled_for - time.time()))
        if wait_seconds:
            add_log(job, f"Campanha agendada para {format_timestamp(job.scheduled_for)}.")
            persist_campaign(job)
            if not sleep_interruptibly(job, wait_seconds):
                with JOB_LOCK:
                    job.finished_at = time.time()
                    job.status = "cancelled"
                add_log(job, "Campanha agendada cancelada antes do início.")
                finish_job(job)
                return
    if job.cancel_event.is_set():
        with JOB_LOCK:
            job.finished_at = time.time()
            job.status = "cancelled"
        add_log(job, "Campanha cancelada antes do início.")
        finish_job(job)
        return
    run_job(
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
        send_copy_to_self,
    )


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
    domain_times: dict[str, float] = {}
    suppression = load_suppression_list()
    context = ssl.create_default_context()
    add_log(job, f"Conectando ao servidor {SMTP_SERVER}:{SMTP_PORT}.")
    persist_campaign(job)
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

                if recipient.email in suppression:
                    with JOB_LOCK:
                        job.skipped += 1
                    detail = f"Supresso: {suppression[recipient.email].get('reason', 'lista de supressão')}"
                    add_log(job, f"{recipient.email} ignorado por lista de supressão.")
                    record_report_row(job, recipient.email, "suppressed", detail)
                    continue

                if not enforce_hourly_limit(job, sent_times, max_per_hour):
                    break
                if not enforce_domain_spacing(job, recipient.email, domain_times):
                    break

                try:
                    message = build_message(job.sender, recipient, job.subject, body, is_html, reply_to)
                    smtp.send_message(message)
                    sent_times.append(time.time())
                    domain_times[recipient_domain(recipient.email)] = time.time()
                    with JOB_LOCK:
                        job.sent += 1
                    add_log(job, f"Enviado para {recipient.email} ({index}/{job.total}).")
                    record_report_row(job, recipient.email, "sent", "Entregue ao servidor SMTP.")
                except Exception as exc:  # noqa: BLE001
                    domain_times[recipient_domain(recipient.email)] = time.time()
                    with JOB_LOCK:
                        job.failed += 1
                    add_log(job, f"Falha ao enviar para {recipient.email}: {exc}")
                    permanent, detail = is_permanent_smtp_error(exc)
                    record_report_row(job, recipient.email, "failed", detail)
                    if permanent:
                        add_suppression(recipient.email, detail)
                        suppression[recipient.email] = {"reason": detail, "created_at": format_timestamp(time.time())}
                        add_log(job, f"{recipient.email} entrou na lista de supressão por falha permanente.")

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
        finish_job(job)
    except Exception as exc:  # noqa: BLE001
        with JOB_LOCK:
            job.current = ""
            job.finished_at = time.time()
            job.status = "failed"
        add_log(job, f"Envio interrompido: {exc}")
        finish_job(job)


def job_snapshot() -> dict[str, Any]:
    with JOB_LOCK:
        job = CURRENT_JOB
        if not job:
            return {"id": None, "status": "idle", "logs": [], "suppression_count": suppression_count()}
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
            "scheduled_for_text": format_timestamp(job.scheduled_for),
            "report_url": f"/api/report?id={job.id}" if job.report_path else "",
            "suppression_count": suppression_count(),
            "logs": list(job.logs),
        }


class MailerHandler(BaseHTTPRequestHandler):
    server_version = "MalaDiretaTCE/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self.send_text(INDEX_HTML, "text/html; charset=utf-8")
            return
        if parsed.path == "/api/status":
            self.send_json(job_snapshot())
            return
        if parsed.path == "/api/history":
            self.send_json(
                {
                    "items": load_history()[:10],
                    "active_items": load_active_campaigns(),
                    "suppression_count": suppression_count(),
                }
            )
            return
        if parsed.path == "/api/report":
            report_id = parse_qs(parsed.query).get("id", [""])[0]
            report_path = REPORTS_DIR / f"{report_id}.csv"
            if not report_id or not report_path.exists():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_bytes(
                report_path.read_bytes(),
                "text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename=\"relatorio-{report_id}.csv\"'},
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/preview":
                self.handle_preview()
            elif parsed.path == "/api/start":
                self.handle_start()
            elif parsed.path == "/api/pause":
                self.handle_pause()
            elif parsed.path == "/api/resume":
                self.handle_resume()
            elif parsed.path == "/api/cancel":
                self.handle_cancel(parsed)
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
            if CURRENT_JOB and CURRENT_JOB.status in {"running", "paused", "scheduled"}:
                raise ValueError("Já existe uma campanha em andamento. Pause, cancele ou aguarde terminar.")
        if has_active_campaign():
            raise ValueError("Já existe uma campanha ativa ou agendada. Conclua ou cancele antes de criar outra.")

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
        scheduled_for = parse_schedule(field_value(fields, "schedule_at"))
        if reply_to and not EMAIL_RE.match(reply_to):
            raise ValueError("O campo Responder para precisa ser um e-mail válido.")
        if scheduled_for and scheduled_for <= time.time():
            scheduled_for = None

        job = MailJob(
            id=str(uuid.uuid4()),
            sender=sender,
            total=len(recipients),
            subject=subject,
            status="scheduled" if scheduled_for else "running",
            skipped=invalid,
            scheduled_for=scheduled_for,
        )
        with JOB_LOCK:
            CURRENT_JOB = job
        add_log(
            job,
            "Campanha criada. Preparando autenticação e fila de envio."
            if not scheduled_for
            else f"Campanha criada e agendada para {format_timestamp(scheduled_for)}.",
        )
        persist_campaign(job)
        if invalid:
            add_log(job, f"{invalid} item(ns) inválido(s) ou duplicado(s) foram ignorados.")

        thread = threading.Thread(
            target=run_scheduled_job if scheduled_for else run_job,
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
        if scheduled_for:
            persist_scheduled_payload(
                job.id,
                build_scheduled_payload(
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
                password,
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
            persist_campaign(job)
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
            persist_campaign(job)
        self.send_json(job_snapshot())

    def handle_cancel(self, parsed: Any) -> None:
        campaign_id = parse_qs(parsed.query).get("id", [""])[0]
        if not campaign_id:
            with JOB_LOCK:
                job = CURRENT_JOB
                campaign_id = job.id if job and job.status in {"running", "paused", "scheduled"} else ""
        if not campaign_id:
            raise ValueError("Nenhuma campanha em andamento foi encontrada para cancelar.")
        if not cancel_campaign_by_id(campaign_id):
            raise ValueError("Não foi possível cancelar a campanha informada.")
        self.send_json(
            {
                "ok": True,
                "job": job_snapshot(),
                "active_items": load_active_campaigns(),
                "items": load_history()[:10],
                "suppression_count": suppression_count(),
            }
        )

    def read_form(self) -> FormData:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("Envie os dados do formulário corretamente.")
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        return parse_multipart_form(raw_body, content_type)

    def send_text(self, content: str, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_bytes(content.encode("utf-8"), content_type, status)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_bytes(raw, "application/json; charset=utf-8", status)

    def send_bytes(
        self,
        raw: bytes,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    init_database()
    restore_scheduled_campaigns()
    httpd = ThreadingHTTPServer((APP_HOST, APP_PORT), MailerHandler)
    print(f"Mala Direta TCE/AL aberta em http://{APP_HOST}:{APP_PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
