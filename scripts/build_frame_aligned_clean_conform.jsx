/* Clone the recovered user conform and replace only frame-proven intervals. */
(function () {
  var ROOT = "/Users/alphaone/Documents/Code/paracosm-provenance";
  var MANIFEST_PATH =
    ROOT + "/data/premiere/frame-aligned-manifest.json";
  var STATUS_PATH =
    ROOT + "/data/premiere/frame-aligned-premiere-status.json";
  var OUTPUT_DIR = ROOT + "/data/premiere";
  var YELLOW_LABEL_INDEX = 15;

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

  function pad(value, width) {
    var text = String(value);
    while (text.length < width) {
      text = "0" + text;
    }
    return text;
  }

  function timestamp() {
    var now = new Date();
    return (
      now.getUTCFullYear() +
      pad(now.getUTCMonth() + 1, 2) +
      pad(now.getUTCDate(), 2) +
      "T" +
      pad(now.getUTCHours(), 2) +
      pad(now.getUTCMinutes(), 2) +
      pad(now.getUTCSeconds(), 2) +
      "Z"
    );
  }

  function findSequence(name) {
    for (var index = 0; index < app.project.sequences.numSequences; index++) {
      if (app.project.sequences[index].name === name) {
        return app.project.sequences[index];
      }
    }
    return null;
  }

  function sequenceIds() {
    var result = {};
    for (var index = 0; index < app.project.sequences.numSequences; index++) {
      result[app.project.sequences[index].sequenceID] = true;
    }
    return result;
  }

  function newSequenceSince(previous) {
    for (var index = 0; index < app.project.sequences.numSequences; index++) {
      var sequence = app.project.sequences[index];
      if (!previous[sequence.sequenceID]) {
        return sequence;
      }
    }
    return null;
  }

  function findChildByName(parent, name) {
    for (var index = 0; index < parent.children.numItems; index++) {
      if (parent.children[index].name === name) {
        return parent.children[index];
      }
    }
    return null;
  }

  function ensureBin(parent, name) {
    return findChildByName(parent, name) || parent.createBin(name);
  }

  function findMediaItem(parent, path) {
    for (var index = 0; index < parent.children.numItems; index++) {
      var child = parent.children[index];
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
        } catch (ignoreMediaPath) {}
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

  function timeFromTicks(ticks) {
    var value = new Time();
    value.ticks = String(ticks);
    return value;
  }

  function clipsOverlapping(track, start, end) {
    var result = [];
    for (var index = 0; index < track.clips.numItems; index++) {
      var clip = track.clips[index];
      if (
        clip.start.seconds < end - 0.001 &&
        clip.end.seconds > start + 0.001
      ) {
        result.push(clip);
      }
    }
    return result;
  }

  function findInsertedClip(track, start, mediaPath) {
    for (var index = 0; index < track.clips.numItems; index++) {
      var clip = track.clips[index];
      var candidatePath = "";
      try {
        candidatePath = clip.projectItem.getMediaPath();
      } catch (ignoreMediaPath) {}
      if (
        candidatePath === mediaPath &&
        Math.abs(clip.start.seconds - start) < 0.03
      ) {
        return clip;
      }
    }
    return null;
  }

  var status = {
    schemaVersion: 1,
    startedAt: new Date().toUTCString(),
    success: false,
    failures: [],
    activeProjectBefore: app.project ? String(app.project.path || "") : "",
    activeProjectBackup: "",
    baseProject: "",
    baseSequence: "",
    outputSequence: "",
    expectedReplacements: 0,
    removedOverlappingClips: 0,
    insertedReplacements: 0,
    verifiedReplacements: 0,
    replacements: []
  };

  try {
    var manifest = readJson(MANIFEST_PATH);
    var baseProjectPath = String(manifest.baseProject);
    var baseSequenceName = String(manifest.baseSequence);
    var outputSequenceName = String(manifest.outputSequence);
    var stamp = timestamp();
    status.baseProject = baseProjectPath;
    status.baseSequence = baseSequenceName;
    status.outputSequence = outputSequenceName;
    status.expectedReplacements = manifest.records.length;

    if (app.project && String(app.project.path || "") !== baseProjectPath) {
      var currentPath = String(app.project.path || "");
      if (currentPath) {
        var backupPath =
          OUTPUT_DIR + "/PRE_SCRIPT_ACTIVE_PROJECT_BACKUP_" + stamp + ".prproj";
        if (!app.project.saveAs(backupPath)) {
          throw new Error("Could not preserve the active project before switching.");
        }
        status.activeProjectBackup = backupPath;
      }
      app.project.closeDocument(false, false);
    }
    if (
      !app.project ||
      String(app.project.path || "") !== baseProjectPath
    ) {
      if (
        !new File(baseProjectPath).exists ||
        !app.openDocument(baseProjectPath, true, true, true, true)
      ) {
        throw new Error("Could not open the recovered canonical base project.");
      }
    }
    if (String(app.project.path || "") !== baseProjectPath) {
      throw new Error("The recovered canonical base project is not active.");
    }

    var base = findSequence(baseSequenceName);
    if (!base) {
      throw new Error('Sequence "' + baseSequenceName + '" was not found.');
    }
    var priorIds = sequenceIds();
    if (!base.clone()) {
      throw new Error("Premiere could not clone the clean conform.");
    }
    var conform = newSequenceSince(priorIds);
    if (!conform) {
      throw new Error("The cloned sequence could not be identified.");
    }
    conform.name = outputSequenceName;
    app.project.openSequence(conform.sequenceID);
    conform = app.project.activeSequence;
    if (!conform || conform.name !== outputSequenceName) {
      throw new Error("Could not activate the frame-aligned clone.");
    }
    if (conform.videoTracks.numTracks < 2) {
      throw new Error("The clean conform does not have V1 and V2.");
    }

    var correctionRanges = [
      {
        start: manifest.records[0].timelineStart,
        end: manifest.records[8].timelineEnd
      },
      {
        start: manifest.records[9].timelineStart,
        end: manifest.records[10].timelineEnd
      }
    ];
    for (var trackIndex = 0; trackIndex < 2; trackIndex++) {
      var cleanTrack = conform.videoTracks[trackIndex];
      for (
        var clipIndex = cleanTrack.clips.numItems - 1;
        clipIndex >= 0;
        clipIndex--
      ) {
        var cleanClip = cleanTrack.clips[clipIndex];
        var shouldRemove = false;
        for (
          var rangeIndex = 0;
          rangeIndex < correctionRanges.length;
          rangeIndex++
        ) {
          var range = correctionRanges[rangeIndex];
          if (
            cleanClip.start.seconds < Number(range.end) - 0.001 &&
            cleanClip.end.seconds > Number(range.start) + 0.001
          ) {
            shouldRemove = true;
          }
        }
        if (shouldRemove) {
          cleanClip.remove(false, false);
          status.removedOverlappingClips++;
        }
      }
    }

    var conformBin = ensureBin(
      app.project.rootItem,
      "PARACOSM FRAME ALIGNED CONFORM"
    );
    var mediaBin = ensureBin(
      conformBin,
      "Reference-frame adapter sequences"
    );
    for (var recordIndex = 0; recordIndex < manifest.records.length; recordIndex++) {
      var record = manifest.records[recordIndex];
      var importPath = String(record.importPath);
      if (!new File(importPath).exists) {
        status.failures.push(record.sourceId + ": adapter first frame is missing");
        continue;
      }
      var projectItem = importSequence(importPath, mediaBin);
      if (!projectItem) {
        status.failures.push(record.sourceId + ": image-sequence import failed");
        continue;
      }
      var frameRateOverridden = false;
      try {
        frameRateOverridden = projectItem.setOverrideFrameRate(
          Number(record.adapterFrameRate)
        );
      } catch (ignoreFrameRate) {}
      try {
        projectItem.setColorLabel(YELLOW_LABEL_INDEX);
      } catch (ignoreLabel) {}
      projectItem.setInPoint(0, 4);
      projectItem.setOutPoint(
        Number(record.timelineFrameCount) / Number(record.adapterFrameRate),
        4
      );

      var targetTrack = conform.videoTracks[Number(record.track) - 1];
      var start = Number(record.timelineStart);
      var end = Number(record.timelineEnd);
      if (clipsOverlapping(targetTrack, start, end).length) {
        status.failures.push(
          record.sourceId + ": corrected interval is not empty on V" + record.track
        );
        continue;
      }
      targetTrack.overwriteClip(projectItem, start);
      var inserted = findInsertedClip(targetTrack, start, importPath);
      if (!inserted) {
        status.failures.push(record.sourceId + ": overwrite created no clip");
        continue;
      }
      inserted.start = timeFromTicks(record.timelineStartTicks);
      inserted.end = timeFromTicks(record.timelineEndTicks);
      inserted.name =
        "FRAME-ALIGNED-" +
        record.sourceId +
        " · " +
        String(record.originalMediaPath).split("/").pop();
      status.insertedReplacements++;

      var startError = Math.abs(inserted.start.seconds - start);
      var endError = Math.abs(inserted.end.seconds - end);
      var verified =
        startError < 0.001 &&
        endError < 0.001 &&
        Math.abs(
          inserted.duration.seconds -
            Number(record.timelineFrameCount) /
              Number(record.adapterFrameRate)
        ) < 0.03;
      if (verified) {
        status.verifiedReplacements++;
      } else {
        status.failures.push(
          record.sourceId +
            ": placement differs from manifest (" +
            startError +
            ", " +
            endError +
            ")"
        );
      }
      status.replacements.push({
        sourceId: record.sourceId,
        track: record.track,
        importPath: importPath,
        originalMediaPath: record.originalMediaPath,
        timelineStartFrame: record.timelineStartFrame,
        timelineEndFrame: record.timelineEndFrame,
        timelineStart: inserted.start.seconds,
        timelineEnd: inserted.end.seconds,
        mediaIn: inserted.inPoint.seconds,
        mediaOut: inserted.outPoint.seconds,
        frameRateOverridden: frameRateOverridden,
        startError: startError,
        endError: endError,
        verified: verified
      });
    }

    var outputStem =
      OUTPUT_DIR + "/Paracosm_Conform_Codex_FRAME_ALIGNED_" + stamp;
    status.projectExport = outputStem + ".prproj";
    status.fcpXml = outputStem + ".xml";
    status.xmlExported = Boolean(
      conform.exportAsFinalCutProXML(status.fcpXml)
    );
    status.projectExported = Boolean(
      conform.exportAsProject(status.projectExport)
    );
    status.success =
      status.insertedReplacements === status.expectedReplacements &&
      status.verifiedReplacements === status.expectedReplacements &&
      status.failures.length === 0 &&
      status.projectExported;
    status.completedAt = new Date().toUTCString();
    writeJson(STATUS_PATH, status);

    if (status.success) {
      app.project.closeDocument(false, false);
      if (app.openDocument(status.projectExport, true, true, true, true)) {
        var exportedSequence = findSequence(outputSequenceName);
        if (exportedSequence) {
          app.project.openSequence(exportedSequence.sequenceID);
        }
      }
    }
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
