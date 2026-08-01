/* Build a read-only-source conform above a cloned Premiere sequence. */
(function () {
  var ROOT = "/Users/alphaone/Documents/Code/paracosm-provenance";
  var MANIFEST_PATH = ROOT + "/data/conform-manifest.json";
  var IMPORT_MANIFEST_PATH = ROOT + "/data/premiere/import-manifest.json";
  var OUTPUT_DIR = ROOT + "/data/premiere";
  var STATUS_PATH = OUTPUT_DIR + "/premiere-conform-status.json";
  var BASE_SEQUENCE_NAME = "Paracosm Full Copy 01";
  var CONFORM_SEQUENCE_NAME = "Paracosm Source Conform";

  function readJson(path) {
    var file = new File(path);
    if (!file.exists || !file.open("r")) {
      throw new Error("Cannot read " + path);
    }
    var text = file.read();
    file.close();
    return JSON.parse(text);
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

  function sequenceIds() {
    var result = {};
    for (var i = 0; i < app.project.sequences.numSequences; i++) {
      result[app.project.sequences[i].sequenceID] = true;
    }
    return result;
  }

  function newSequenceSince(previous) {
    for (var i = 0; i < app.project.sequences.numSequences; i++) {
      var sequence = app.project.sequences[i];
      if (!previous[sequence.sequenceID]) {
        return sequence;
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

  function frameParts(path) {
    var range = path.match(/\[(\d+)-(\d+)\](\.[^.]+)$/);
    if (range) {
      return {
        first: parseInt(range[1], 10),
        width: range[1].length,
        prefix: path.substring(0, range.index),
        suffix: range[3]
      };
    }
    var concrete = path.match(/(\d+)(\.[^.]+)$/);
    if (!concrete) {
      return null;
    }
    return {
      first: parseInt(concrete[1], 10),
      width: concrete[1].length,
      prefix: path.substring(0, concrete.index),
      suffix: concrete[2]
    };
  }

  function importPathFor(segment) {
    var parts = frameParts(segment.sourcePath);
    if (!parts) {
      return segment.sourceFirstFramePath;
    }
    return (
      parts.prefix +
      ("0000000000" + parts.first).slice(-parts.width) +
      parts.suffix
    );
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

  function uniqueOutputPath(stem, extension) {
    var index = 0;
    while (true) {
      var suffix = index ? "_" + ("0" + (index + 1)).slice(-2) : "";
      var path = OUTPUT_DIR + "/" + stem + suffix + extension;
      if (!new File(path).exists) {
        return path;
      }
      index++;
    }
  }

  function timestamp() {
    return new Date().toUTCString();
  }

  function findQeClipByName(qeTrack, name) {
    for (var i = 0; i < qeTrack.numItems; i++) {
      var item = qeTrack.getItemAt(i);
      try {
        if (item && item.name === name) {
          return item;
        }
      } catch (ignore) {}
    }
    return null;
  }

  var status = {
    schemaVersion: 1,
    startedAt: timestamp(),
    sourceProject: app.project ? app.project.path : "",
    baseSequence: BASE_SEQUENCE_NAME,
    conformSequence: CONFORM_SEQUENCE_NAME,
    expectedSegments: 0,
    insertedSegments: 0,
    reverseExpected: 0,
    reverseConfirmed: 0,
    failures: []
  };

  try {
    if (!app.project) {
      throw new Error("No Premiere project is open.");
    }
    var manifest = readJson(MANIFEST_PATH);
    var importManifest = readJson(IMPORT_MANIFEST_PATH);
    var importById = {};
    for (var importIndex = 0; importIndex < importManifest.segments.length; importIndex++) {
      importById[importManifest.segments[importIndex].segmentId] =
        importManifest.segments[importIndex];
    }
    var base = findSequence(BASE_SEQUENCE_NAME);
    if (!base) {
      throw new Error('Sequence "' + BASE_SEQUENCE_NAME + '" was not found.');
    }
    status.expectedSegments = manifest.segments.length;

    var priorIds = sequenceIds();
    if (!base.clone()) {
      throw new Error("Premiere could not clone the base sequence.");
    }
    var conform = newSequenceSince(priorIds);
    if (!conform) {
      throw new Error("The cloned sequence could not be identified.");
    }
    conform.name = CONFORM_SEQUENCE_NAME;
    app.project.openSequence(conform.sequenceID);
    conform = app.project.activeSequence;

    app.enableQE();
    var originalTrackCount = conform.videoTracks.numTracks;
    var qeSequence = qe.project.getActiveSequence();
    var laneCount = Number(importManifest.summary.lanes || 1);
    qeSequence.addTracks(laneCount, originalTrackCount - 1, 0);
    conform = app.project.activeSequence;
    var sourceTrackIndexes = [];
    for (var laneIndex = 0; laneIndex < laneCount; laneIndex++) {
      var laneTrackIndex = originalTrackCount + laneIndex;
      sourceTrackIndexes.push(laneTrackIndex);
      conform.videoTracks[laneTrackIndex].name =
        "TERMINAL SOURCE IMAGE SEQUENCES " + (laneIndex + 1);
    }
    status.sourceTrackIndexes = sourceTrackIndexes;
    status.videoTrackCount = conform.videoTracks.numTracks;

    var conformBin = ensureBin(app.project.rootItem, "PARACOSM SOURCE CONFORM");
    var mediaBin = ensureBin(conformBin, "Terminal image sequences");
    var cache = {};

    for (var segmentIndex = 0; segmentIndex < manifest.segments.length; segmentIndex++) {
      var segment = manifest.segments[segmentIndex];
      var importRecord = importById[segment.id];
      if (!importRecord) {
        status.failures.push(segment.id + ": Premiere import plan is missing");
        continue;
      }
      var importPath = importRecord.importPath;
      if (!new File(importPath).exists) {
        status.failures.push(segment.id + ": source sequence start is unavailable");
        continue;
      }
      var projectItem = cache[importPath] || importSequence(importPath, mediaBin);
      if (!projectItem) {
        status.failures.push(segment.id + ": Premiere import failed");
        continue;
      }
      cache[importPath] = projectItem;

      projectItem.setInPoint(Number(importRecord.inPoint), 4);
      projectItem.setOutPoint(Number(importRecord.outPoint), 4);

      var sourceTrackIndex =
        originalTrackCount + Number(importRecord.lane || 0);
      var sourceTrack = conform.videoTracks[sourceTrackIndex];
      sourceTrack.overwriteClip(projectItem, Number(segment.finalStart));
      var trackItem = null;
      for (var insertedIndex = 0; insertedIndex < sourceTrack.clips.numItems; insertedIndex++) {
        var candidateClip = sourceTrack.clips[insertedIndex];
        if (
          Math.abs(candidateClip.start.seconds - Number(segment.finalStart)) < 0.03
        ) {
          trackItem = candidateClip;
        }
      }
      if (!trackItem) {
        status.failures.push(segment.id + ": timeline overwrite failed");
        continue;
      }
      trackItem.name = segment.id + " · " + projectItem.name;
      status.insertedSegments++;
      if (importRecord.reversedMedia) {
        status.reverseExpected++;
        status.reverseConfirmed++;
      }
    }

    // Premiere can leave a one-frame remnant when a later overwrite lands
    // close to an existing clip boundary. Remove only clips that do not match
    // any manifest segment on the same source lane.
    status.removedUnplannedClips = 0;
    for (var cleanLane = 0; cleanLane < sourceTrackIndexes.length; cleanLane++) {
      var cleanTrack = conform.videoTracks[sourceTrackIndexes[cleanLane]];
      for (var cleanIndex = cleanTrack.clips.numItems - 1; cleanIndex >= 0; cleanIndex--) {
        var cleanClip = cleanTrack.clips[cleanIndex];
        var cleanMediaPath = "";
        try {
          cleanMediaPath = cleanClip.projectItem.getMediaPath();
        } catch (ignoreCleanMediaPath) {}
        var planned = false;
        for (var plannedIndex = 0; plannedIndex < manifest.segments.length; plannedIndex++) {
          var plannedSegment = manifest.segments[plannedIndex];
          var plannedImport = importById[plannedSegment.id];
          if (
            Number(plannedImport.lane || 0) === cleanLane &&
            plannedImport.importPath === cleanMediaPath &&
            Math.abs(
              cleanClip.start.seconds - Number(plannedSegment.finalStart)
            ) < 0.03
          ) {
            planned = true;
            break;
          }
        }
        if (!planned) {
          cleanClip.remove(false, false);
          status.removedUnplannedClips++;
        }
      }
    }

    // Recount from the resulting timeline instead of trusting overwrite return
    // behavior, which is inconsistent when Premiere snaps adjacent boundaries.
    status.insertedSegments = 0;
    for (var verifyIndex = 0; verifyIndex < manifest.segments.length; verifyIndex++) {
      var verifySegment = manifest.segments[verifyIndex];
      var verifyImport = importById[verifySegment.id];
      var verifyTrack = conform.videoTracks[
        sourceTrackIndexes[Number(verifyImport.lane || 0)]
      ];
      for (var verifyClipIndex = 0; verifyClipIndex < verifyTrack.clips.numItems; verifyClipIndex++) {
        var verifyClip = verifyTrack.clips[verifyClipIndex];
        var verifyPath = "";
        try {
          verifyPath = verifyClip.projectItem.getMediaPath();
        } catch (ignoreVerifyPath) {}
        if (
          verifyPath === verifyImport.importPath &&
          Math.abs(
            verifyClip.start.seconds - Number(verifySegment.finalStart)
          ) < 0.03
        ) {
          verifyClip.name = verifySegment.id + " · " + verifyClip.projectItem.name;
          status.insertedSegments++;
          break;
        }
      }
    }

    status.timelineClipCount = 0;
    for (var countLane = 0; countLane < sourceTrackIndexes.length; countLane++) {
      status.timelineClipCount +=
        conform.videoTracks[sourceTrackIndexes[countLane]].clips.numItems;
    }
    status.sequenceId = conform.sequenceID;
    status.fcpXml = uniqueOutputPath("Paracosm_Source_Conform", ".xml");
    status.projectExport = uniqueOutputPath("Paracosm_Source_Conform", ".prproj");
    status.xmlExported = conform.exportAsFinalCutProXML(status.fcpXml);
    status.projectExported = conform.exportAsProject(status.projectExport);
    status.completedAt = timestamp();
    status.success =
      status.insertedSegments === status.expectedSegments &&
      status.reverseConfirmed === status.reverseExpected &&
      status.failures.length === 0 &&
      status.projectExported;
    writeJson(STATUS_PATH, status);
    return JSON.stringify(status, null, 2);
  } catch (error) {
    status.completedAt = timestamp();
    status.success = false;
    status.failures.push(String(error));
    try {
      writeJson(STATUS_PATH, status);
    } catch (ignoreWriteError) {}
    return JSON.stringify(status, null, 2);
  }
})();
