/* Insert verified/candidate source renders onto their semantic V5-V7 tracks. */
(function () {
  var ROOT = "/Users/alphaone/Documents/Code/paracosm-provenance";
  var CONFIRMATIONS_PATH = ROOT + "/data/source-confirmations.json";
  var REVISED_PATH = ROOT + "/data/premiere/revised-conform-export.json";
  var OUTPUT_DIR = ROOT + "/data/premiere";
  var STATUS_PATH = OUTPUT_DIR + "/recovered-sources-status.json";
  var VERIFIED_PROJECT_PATH =
    OUTPUT_DIR + "/Paracosm_Source_Conform_VERIFIED_V2.prproj";
  var SEQUENCE_NAME = "Paracosm Source Conform";
  var EXPORT_SEQUENCE_NAME =
    "Paracosm Source Conform YELLOW RECOVERIES NATIVE";
  var SOURCE_FRAME_RATE = 24.0;
  var YELLOW_LABEL_INDEX = 15;
  var ALLOWED_TRACKS = {5: true, 6: true, 7: true};

  function readJson(path) {
    var file = new File(path);
    if (!file.exists || !file.open("r")) {
      throw new Error("Cannot read " + path);
    }
    var value = JSON.parse(file.read());
    file.close();
    return value;
  }

  function writeJson(path, value) {
    var file = new File(path);
    file.encoding = "UTF-8";
    if (!file.open("w")) {
      throw new Error("Cannot write " + path);
    }
    file.write(JSON.stringify(value, null, 2));
    file.close();
  }

  function findSequence(name) {
    for (var i = 0; i < app.project.sequences.numSequences; i++) {
      if (app.project.sequences[i].name === name) {
        return app.project.sequences[i];
      }
    }
    return null;
  }

  function findChildByName(parent, name) {
    for (var i = 0; i < parent.children.numItems; i++) {
      if (parent.children[i].name === name) {
        return parent.children[i];
      }
    }
    return null;
  }

  function ensureBin(parent, name) {
    return findChildByName(parent, name) || parent.createBin(name);
  }

  function findMediaItem(parent, path) {
    for (var i = 0; i < parent.children.numItems; i++) {
      var child = parent.children[i];
      if (child.type === ProjectItemType.BIN) {
        var nested = findMediaItem(child, path);
        if (nested) {
          return nested;
        }
      } else {
        try {
          if (child.getMediaPath && child.getMediaPath() === path) {
            return child;
          }
        } catch (ignore) {}
      }
    }
    return null;
  }

  function importSequence(path, bin) {
    var existing = findMediaItem(app.project.rootItem, path);
    if (existing) {
      return existing;
    }
    if (!app.project.importFiles([path], true, bin, true)) {
      return null;
    }
    return findMediaItem(app.project.rootItem, path);
  }

  function timestampStem() {
    var now = new Date();
    function pad(value) {
      return ("0" + value).slice(-2);
    }
    return (
      now.getUTCFullYear() +
      "-" +
      pad(now.getUTCMonth() + 1) +
      "-" +
      pad(now.getUTCDate()) +
      "_" +
      pad(now.getUTCHours()) +
      pad(now.getUTCMinutes()) +
      pad(now.getUTCSeconds())
    );
  }

  function clipsOverlapping(track, start, end) {
    var result = [];
    for (var i = 0; i < track.clips.numItems; i++) {
      var clip = track.clips[i];
      if (clip.start.seconds < end - 0.001 && clip.end.seconds > start + 0.001) {
        result.push(clip);
      }
    }
    return result;
  }

  var status = {
    schemaVersion: 1,
    startedAt: new Date().toUTCString(),
    activeProject: app.project ? app.project.path : "",
    sequence: SEQUENCE_NAME,
    targetTracks: "V5 older / V6 exact / V7 newer",
    requestedLabel: "Yellow",
    requestedLabelIndex: YELLOW_LABEL_INDEX,
    expected: 0,
    inserted: 0,
    verified: 0,
    failures: [],
    v1Touched: false,
    sourceProjectSaved: false,
    success: false
  };

  try {
    if (!app.project) {
      throw new Error("No Premiere project is open.");
    }
    var activeProjectPath = String(app.project.path);
    if (
      activeProjectPath.indexOf(
        "/Paracosm_Source_Conform_VERIFIED_V2.prproj"
      ) !== -1
    ) {
      app.project.closeDocument(false, false);
      activeProjectPath = "";
    }
    if (
      activeProjectPath.indexOf(
        "/Paracosm_Source_Conform_VERIFIED_V2.prproj"
      ) === -1
    ) {
      if (
        !new File(VERIFIED_PROJECT_PATH).exists ||
        !app.openDocument(
          VERIFIED_PROJECT_PATH,
          true,
          true,
          true,
          true
        )
      ) {
        throw new Error("Could not open the protected VERIFIED_V2 project.");
      }
      activeProjectPath = String(app.project.path);
    }
    if (
      activeProjectPath.indexOf(
        "/Paracosm_Source_Conform_VERIFIED_V2.prproj"
      ) === -1
    ) {
      throw new Error(
        "The protected VERIFIED_V2 project is not active."
      );
    }
    status.activeProject = activeProjectPath;
    var sequence = findSequence(SEQUENCE_NAME);
    if (!sequence) {
      throw new Error('Sequence "' + SEQUENCE_NAME + '" was not found.');
    }
    app.project.openSequence(sequence.sequenceID);
    sequence = app.project.activeSequence;
    if (!sequence || sequence.name !== SEQUENCE_NAME) {
      throw new Error("Could not activate the conform sequence.");
    }
    if (sequence.videoTracks.numTracks < 7) {
      throw new Error("The conform does not contain all V5-V7 source tracks.");
    }

    var confirmations = readJson(CONFIRMATIONS_PATH);
    var revised = readJson(REVISED_PATH);
    var editsByCut = {};
    for (var editIndex = 0; editIndex < revised.inventory.length; editIndex++) {
      var edit = revised.inventory[editIndex];
      if (edit.role === "final_cut" && edit.canonicalId) {
        editsByCut[edit.canonicalId] = edit;
      }
    }
    var placements = [];
    for (
      var confirmationIndex = 0;
      confirmationIndex < confirmations.confirmations.length;
      confirmationIndex++
    ) {
      var confirmation = confirmations.confirmations[confirmationIndex];
      var conformTrack = Number(confirmation.conformTrack);
      if (
        (confirmation.status === "confirmed" ||
          confirmation.status === "candidate") &&
        ALLOWED_TRACKS[conformTrack]
      ) {
        placements.push(confirmation);
      }
    }
    status.expected = placements.length;

    var conformBin = ensureBin(app.project.rootItem, "PARACOSM SOURCE CONFORM");
    var recoveredBin = ensureBin(conformBin, "Recovered yellow source candidates");

    for (var index = 0; index < placements.length; index++) {
      var record = placements[index];
      var editRecord = editsByCut[record.cutId];
      if (!editRecord) {
        status.failures.push(record.cutId + ": V1 cut was not found");
        continue;
      }
      var start = Number(editRecord.start);
      var end = Number(editRecord.end);
      var duration = end - start;
      var trackNumber = Number(record.conformTrack);
      var targetTrack = sequence.videoTracks[trackNumber - 1];
      var overlaps = clipsOverlapping(targetTrack, start, end);
      if (overlaps.length) {
        status.failures.push(
          record.cutId +
            ": V" +
            trackNumber +
            " is not empty across the authoritative V1 interval"
        );
        continue;
      }
      var sourcePath = String(record.sourcePath);
      if (!new File(sourcePath).exists) {
        status.failures.push(record.cutId + ": source first frame is missing");
        continue;
      }
      var projectItem = importSequence(sourcePath, recoveredBin);
      if (!projectItem) {
        status.failures.push(record.cutId + ": numbered-still import failed");
        continue;
      }
      var nativeDuration = null;
      try {
        nativeDuration = projectItem.getOutPoint().seconds;
      } catch (ignoreNativeDuration) {}
      if (nativeDuration !== null && nativeDuration > 3600) {
        status.failures.push(
          record.cutId +
            ": Premiere interpreted the source as a held still (" +
            nativeDuration +
            " seconds)"
        );
        continue;
      }
      var frameRateOverridden = false;
      try {
        frameRateOverridden =
          projectItem.setOverrideFrameRate(SOURCE_FRAME_RATE);
      } catch (ignoreFrameRate) {}
      var interpretedFrameRate = null;
      try {
        interpretedFrameRate =
          projectItem.getFootageInterpretation().frameRate;
      } catch (ignoreInterpretation) {}
      if (
        interpretedFrameRate !== null &&
        Math.abs(interpretedFrameRate - SOURCE_FRAME_RATE) > 0.001
      ) {
        status.failures.push(
          record.cutId +
            ": source frame rate is " +
            interpretedFrameRate +
            ", expected " +
            SOURCE_FRAME_RATE
        );
        continue;
      }
      projectItem.setInPoint(0, 4);
      projectItem.setOutPoint(duration, 4);
      try {
        projectItem.setColorLabel(YELLOW_LABEL_INDEX);
      } catch (ignoreLabel) {}
      targetTrack.overwriteClip(projectItem, start);

      var inserted = null;
      for (
        var clipIndex = 0;
        clipIndex < targetTrack.clips.numItems;
        clipIndex++
      ) {
        var candidate = targetTrack.clips[clipIndex];
        if (Math.abs(candidate.start.seconds - start) < 0.03) {
          inserted = candidate;
        }
      }
      if (!inserted) {
        status.failures.push(record.cutId + ": overwrite did not create a clip");
        continue;
      }
      var exactEnd = new Time();
      exactEnd.ticks = String(editRecord.endTicks);
      inserted.end = exactEnd;
      inserted.name =
        "YELLOW-" +
        record.status.toUpperCase() +
        "-" +
        record.cutId +
        " · " +
        projectItem.name;
      status.inserted++;
      var startError = Math.abs(inserted.start.seconds - start);
      var endError = Math.abs(inserted.end.seconds - end);
      status[record.cutId] = {
        sourcePath: sourcePath,
        status: record.status,
        conformRole: record.conformRole,
        track: trackNumber,
        timelineStart: inserted.start.seconds,
        timelineEnd: inserted.end.seconds,
        authoritativeStart: start,
        authoritativeEnd: end,
        startError: startError,
        endError: endError,
        mediaIn: inserted.inPoint.seconds,
        mediaOut: inserted.outPoint.seconds,
        nativeSequenceDuration: nativeDuration,
        sourceFrameRate: interpretedFrameRate,
        sourceFrameRateOverridden: frameRateOverridden,
        label: projectItem.getColorLabel ? projectItem.getColorLabel() : null
      };
      if (startError < 0.001 && endError < 0.03) {
        status.verified++;
      } else {
        status.failures.push(
          record.cutId +
            ": inserted timing differs from V1 (" +
            startError +
            ", " +
            endError +
            ")"
        );
      }
    }

    var stem =
      OUTPUT_DIR + "/Paracosm_Source_Conform_YELLOW_RECOVERIES_" + timestampStem();
    status.projectExport = stem + ".prproj";
    status.fcpXml = stem + ".xml";
    var originalSequenceName = sequence.name;
    sequence.name = EXPORT_SEQUENCE_NAME;
    status.sequence = EXPORT_SEQUENCE_NAME;
    status.xmlExported = sequence.exportAsFinalCutProXML(status.fcpXml);
    status.projectExported = sequence.exportAsProject(status.projectExport);
    sequence.name = originalSequenceName;
    status.completedAt = new Date().toUTCString();
    status.success =
      status.inserted === status.expected &&
      status.verified === status.expected &&
      status.failures.length === 0 &&
      status.projectExported;
    writeJson(STATUS_PATH, status);
    return JSON.stringify(status, null, 2);
  } catch (error) {
    status.completedAt = new Date().toUTCString();
    status.failures.push(String(error));
    try {
      writeJson(STATUS_PATH, status);
    } catch (ignoreWrite) {}
    return JSON.stringify(status, null, 2);
  }
})();
