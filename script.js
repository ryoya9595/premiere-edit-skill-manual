// ===== コピー用テキスト（<pre id="..."> に流し込む） =====
const GUIDE_URL = "https://ryoya9595.github.io/premiere-edit-skill-manual/files/claude-code-guide.md";

const INSTALL_PROMPT = `YouTube動画をPremiereでカット編集するスキルを、私のPCに一緒に作ってください。

【手順書】
${GUIDE_URL}

【進め方】
1. 手順書を PowerShell の Invoke-WebRequest（Macなら curl）でダウンロードして、全文を読んでください。
   ※ 要約して読むツールではなく、ファイルの原文を読んでください。
2. 手順書のフェーズA（環境の確認）→ B（Premiere MCPの導入）→ C（スキル作成）→ D（動作確認）の順に進めてください。
3. 各フェーズの終わりに、何をやったかを短く報告してください。

【守ってほしいこと】
- インストール・レジストリ・設定ファイルを変える前は、何をするか説明して私に確認してください。
- 元の動画ファイルは上書き・移動・削除しないでください。
- .env など認証情報のファイルは読まないでください。
- 動作確認は1〜2分の短い動画でやりましょう。どの動画を使うかは私に聞いてください。`;

const RESUME_PROMPT = `Claude Codeを再起動しました。
${GUIDE_URL}
の手順書の、フェーズBの接続確認（verify_premiere_connection）から続けてください。`;

const USE_PROMPT = `この動画を編集して：D:\\動画\\撮影.mp4
固有名詞：Claude, Premiere, Fable`;

const TUNE_PROMPT = `今回の修正を、次からもそうなるようにスキルに反映して。
（例：間はもう少し残して0.3秒くらい／字幕は1枚14文字まで／「えー」「あのー」も切る）`;

const TEXTS = {
  installPrompt: INSTALL_PROMPT,
  resumePrompt: RESUME_PROMPT,
  usePrompt: USE_PROMPT,
  tunePrompt: TUNE_PROMPT,
};

// 各 <pre> に本文を流し込む
Object.entries(TEXTS).forEach(([id, text]) => {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
});

// ===== コピー処理 =====
async function copyText(text, target) {
  let ok = false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      ok = true;
    }
  } catch { ok = false; }
  if (!ok && target) {
    const range = document.createRange();
    range.selectNodeContents(target);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    sel.removeAllRanges();
  }
  return ok;
}

function showToast(msg) {
  let toast = document.getElementById("toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toast";
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 1800);
}

document.querySelectorAll(".copy-btn").forEach((button) => {
  button.addEventListener("click", async () => {
    const targetId = button.dataset.target;
    const target = document.getElementById(targetId);
    const text = TEXTS[targetId] || (target ? target.textContent : "");
    const ok = await copyText(text, target);
    const original = button.textContent;
    button.textContent = ok ? "コピーしました" : "手動でコピー";
    button.classList.toggle("done", ok);
    showToast(ok ? "📋 コピーしました" : "コピーできませんでした");
    setTimeout(() => {
      button.textContent = original;
      button.classList.remove("done");
    }, 2000);
  });
});

// ===== ナビ現在地ハイライト =====
const navLinks = Array.from(document.querySelectorAll(".topnav a[href^='#']"));
const sections = navLinks
  .map((a) => document.querySelector(a.getAttribute("href")))
  .filter(Boolean);
if ("IntersectionObserver" in window && sections.length) {
  const obs = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) {
        const id = "#" + e.target.id;
        navLinks.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === id));
      }
    });
  }, { rootMargin: "-45% 0px -50% 0px" });
  sections.forEach((s) => obs.observe(s));
}
