(function () {
  var button = document.getElementById("run");
  var exportCleanButton = document.getElementById("export-clean");
  var frameAlignedButton = document.getElementById("frame-aligned");
  var status = document.getElementById("status");
  var scriptPath =
    "/Users/alphaone/Documents/Code/paracosm-provenance/scripts/insert_recovered_iris.jsx";
  var exportCleanScriptPath =
    "/Users/alphaone/Documents/Code/paracosm-provenance/scripts/export_clean_conform.jsx";
  var frameAlignedScriptPath =
    "/Users/alphaone/Documents/Code/paracosm-provenance/scripts/build_frame_aligned_clean_conform.jsx";

  function runScript(path, pendingText, buttonElement) {
    buttonElement.disabled = true;
    status.textContent = pendingText;
    var escaped = path.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    window.__adobe_cep__.evalScript(
      '$.evalFile("' + escaped + '")',
      function (result) {
        status.textContent = result || "Premiere returned no result.";
        buttonElement.disabled = false;
      },
    );
  }

  button.addEventListener("click", function () {
    runScript(
      scriptPath,
      "Inserting Yellow recoveries onto V5-V7…",
      button,
    );
  });

  exportCleanButton.addEventListener("click", function () {
    runScript(
      exportCleanScriptPath,
      "Exporting the Clean conform, XML, and exact clip inventory…",
      exportCleanButton,
    );
  });

  frameAlignedButton.addEventListener("click", function () {
    runScript(
      frameAlignedScriptPath,
      "Backing up the active project and building the frame-aligned clone…",
      frameAlignedButton,
    );
  });
})();
