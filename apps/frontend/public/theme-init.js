// Apply cached theme before first paint to prevent flash on login screen
(function () {
  try {
    var theme = localStorage.getItem("wealthfolio-theme") || "system";
    var resolved =
      theme === "system"
        ? window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark"
          : "light"
        : theme === "dark"
          ? "dark"
          : "light";
    document.documentElement.classList.add(resolved);
    document.documentElement.style.colorScheme = resolved;
    // The CSS shows Classic for an ID it doesn't know.
    var themeId = localStorage.getItem("wealthfolio-theme-id");
    if (themeId) document.documentElement.setAttribute("data-theme", themeId);
    // Likewise the default text size for a name it doesn't know.
    var textSize = localStorage.getItem("wealthfolio-text-size");
    if (textSize) document.documentElement.setAttribute("data-text-size", textSize);
    // The CSS shows green up for gain and loss colours it doesn't know.
    var gainColors = localStorage.getItem("wealthfolio-gain-colors");
    if (gainColors) document.documentElement.setAttribute("data-gain-colors", gainColors);
  } catch (e) {}
  // Presentation hint only; profile access is still checked by the app.
  try {
    var opening = JSON.parse(sessionStorage.getItem("wealthfolio-profile-opening") || "null");
    var age = opening && Date.now() - opening.at;
    if (opening && typeof opening.at === "number" && age >= 0 && age < 300000) {
      document.documentElement.classList.add("profile-opening");
    }
  } catch (e) {}
})();
