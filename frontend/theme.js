// Seletor de tema de fundo — independente da lógica de chat em app.js.
// Guarda a escolha em localStorage para persistir entre visitas.
(() => {
  const STORAGE_KEY = "assistente_bg_theme";
  const PADRAO = "gemini";

  const raiz = document.documentElement;
  const botao = document.getElementById("theme-toggle");
  const menu = document.getElementById("theme-menu");

  if (!botao || !menu) return;

  const swatches = Array.from(menu.querySelectorAll(".theme-swatch"));

  function aplicarTema(nome) {
    raiz.setAttribute("data-bg-theme", nome);
    swatches.forEach((sw) => sw.classList.toggle("is-active", sw.dataset.theme === nome));
  }

  function fecharMenu() {
    menu.hidden = true;
    botao.setAttribute("aria-expanded", "false");
  }

  function abrirMenu() {
    menu.hidden = false;
    botao.setAttribute("aria-expanded", "true");
  }

  aplicarTema(localStorage.getItem(STORAGE_KEY) || PADRAO);

  botao.addEventListener("click", (evento) => {
    evento.stopPropagation();
    if (menu.hidden) abrirMenu();
    else fecharMenu();
  });

  swatches.forEach((sw) => {
    sw.addEventListener("click", () => {
      aplicarTema(sw.dataset.theme);
      localStorage.setItem(STORAGE_KEY, sw.dataset.theme);
      fecharMenu();
    });
  });

  document.addEventListener("click", (evento) => {
    if (!menu.hidden && !menu.contains(evento.target) && evento.target !== botao) {
      fecharMenu();
    }
  });

  document.addEventListener("keydown", (evento) => {
    if (evento.key === "Escape") fecharMenu();
  });
})();
