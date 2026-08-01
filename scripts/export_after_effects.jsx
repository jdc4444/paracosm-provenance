(function exportParacosmAfterEffects() {
  var outputPath =
    typeof PARACOSM_OUTPUT_PATH !== "undefined"
      ? PARACOSM_OUTPUT_PATH
      : "/Users/alphaone/Documents/Code/paracosm-provenance/data/after-effects-export.json";
  var projectPaths =
    typeof PARACOSM_PROJECT_PATHS !== "undefined"
      ? PARACOSM_PROJECT_PATHS
      : [
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/AS/1 Edit/paracosm (converted).aep",
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/SG/AE/proj/GG_Edit_v006 (as) 2_1_1 JD.aep",
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/AS/1 Edit/Paracosm IJDKYY.aep",
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/SG/AE/proj/ND_edit_v013.aep",
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/SG/AE/proj/TH_Edit_v001.aep"
  ];

  function clean(value) {
    if (value === undefined || value === null) return null;
    return value;
  }

  function isoNow() {
    function pad(value) {
      return value < 10 ? "0" + value : String(value);
    }
    var date = new Date();
    return (
      date.getUTCFullYear() +
      "-" +
      pad(date.getUTCMonth() + 1) +
      "-" +
      pad(date.getUTCDate()) +
      "T" +
      pad(date.getUTCHours()) +
      ":" +
      pad(date.getUTCMinutes()) +
      ":" +
      pad(date.getUTCSeconds()) +
      "Z"
    );
  }

  function sourceInfo(layer) {
    var source = layer.source;
    if (!source)
      return {
        name: null,
        path: null,
        kind: null,
        duration: null,
        frameRate: null
      };
    var path = null;
    try {
      if (source.file) path = source.file.fsName;
    } catch (ignore) {}
    return {
      name: clean(source.name),
      path: path,
      kind: source instanceof CompItem ? "composition" : "footage",
      duration: clean(source.duration),
      frameRate: clean(source.frameRate)
    };
  }

  function exportLayer(layer) {
    var source = sourceInfo(layer);
    return {
      index: layer.index,
      name: layer.name,
      enabled: layer.enabled,
      inPoint: layer.inPoint,
      outPoint: layer.outPoint,
      startTime: layer.startTime,
      stretch: layer.stretch,
      sourceName: source.name,
      sourcePath: source.path,
      sourceKind: source.kind,
      sourceDuration: source.duration,
      sourceFrameRate: source.frameRate,
      adjustmentLayer: layer.adjustmentLayer,
      guideLayer: layer.guideLayer,
      threeDLayer: layer.threeDLayer,
      timeRemapEnabled: clean(layer.timeRemapEnabled),
      isCamera: layer instanceof CameraLayer
    };
  }

  function exportComp(comp) {
    var layers = [];
    for (var layerIndex = 1; layerIndex <= comp.numLayers; layerIndex += 1) {
      try {
        layers.push(exportLayer(comp.layer(layerIndex)));
      } catch (error) {
        layers.push({
          index: layerIndex,
          name: comp.layer(layerIndex).name,
          error: error.toString()
        });
      }
    }
    return {
      id: comp.id,
      name: comp.name,
      width: comp.width,
      height: comp.height,
      duration: comp.duration,
      frameRate: comp.frameRate,
      workAreaStart: comp.workAreaStart,
      workAreaDuration: comp.workAreaDuration,
      numLayers: comp.numLayers,
      layers: layers
    };
  }

  var result = {
    exportedAt: isoNow(),
    afterEffectsVersion: app.version,
    projects: []
  };

  function writeResult() {
    var output = new File(outputPath);
    output.encoding = "UTF-8";
    if (!output.open("w")) throw new Error("Cannot write " + outputPath);
    output.write(JSON.stringify(result, null, 2));
    output.close();
  }

  app.beginSuppressDialogs();
  for (var projectIndex = 0; projectIndex < projectPaths.length; projectIndex += 1) {
    var projectPath = projectPaths[projectIndex];
    var entry = {
      path: projectPath,
      compositions: [],
      renderQueue: [],
      errors: []
    };
    try {
      var file = new File(projectPath);
      if (!file.exists) throw new Error("Project does not exist");
      app.open(file);
      entry.name = app.project.file ? app.project.file.name : file.name;
      entry.numItems = app.project.numItems;
      for (var itemIndex = 1; itemIndex <= app.project.numItems; itemIndex += 1) {
        var item = app.project.item(itemIndex);
        if (item instanceof CompItem) {
          try {
            entry.compositions.push(exportComp(item));
          } catch (compError) {
            entry.errors.push(item.name + ": " + compError.toString());
          }
        }
      }
      entry.activeItem = app.project.activeItem
        ? clean(app.project.activeItem.name)
        : null;
      for (
        var queueIndex = 1;
        queueIndex <= app.project.renderQueue.numItems;
        queueIndex += 1
      ) {
        var queueItem = app.project.renderQueue.item(queueIndex);
        var outputs = [];
        for (
          var outputIndex = 1;
          outputIndex <= queueItem.numOutputModules;
          outputIndex += 1
        ) {
          var outputModule = queueItem.outputModule(outputIndex);
          outputs.push({
            index: outputIndex,
            file: outputModule.file ? outputModule.file.fsName : null
          });
        }
        entry.renderQueue.push({
          index: queueIndex,
          compName: queueItem.comp ? queueItem.comp.name : null,
          render: queueItem.render,
          status: queueItem.status,
          timeSpanStart: queueItem.timeSpanStart,
          timeSpanDuration: queueItem.timeSpanDuration,
          outputs: outputs
        });
      }
      app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);
    } catch (projectError) {
      entry.errors.push(projectError.toString());
      try {
        if (app.project) app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);
      } catch (closeError) {}
    }
    result.projects.push(entry);
    result.exportedAt = isoNow();
    writeResult();
  }
  app.endSuppressDialogs(false);

  writeResult();
})();
