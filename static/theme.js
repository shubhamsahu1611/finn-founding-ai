function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]').content =
    theme === "dark" ? "#151520" : "#f6f6fa";
}

let initialTheme;
try {
  initialTheme = localStorage.getItem("finn-theme");
} catch {
  // A browser can disable local storage.
}
applyTheme(["light", "dark"].includes(initialTheme)
  ? initialTheme
  : matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
