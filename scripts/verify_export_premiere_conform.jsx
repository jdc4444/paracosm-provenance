/* Verify the active Paracosm conform sequence and export a standalone project. */
(function () {
  var ROOT = "/Users/alphaone/Documents/Code/paracosm-provenance";
  var MANIFEST_PATH = ROOT + "/data/conform-manifest.json";
  var IMPORT_PATH = ROOT + "/data/premiere/import-manifest.json";
  var STATUS_PATH = ROOT + "/data/premiere/premiere-conform-status.json";
  var PROJECT_PATH = ROOT + "/data/premiere/Paracosm_Source_Conform_VERIFIED_V2.prproj";
  var XML_PATH = ROOT + "/data/premiere/Paracosm_Source_Conform_VERIFIED_V2.xml";

  function readJson(path) {
    var file = new File(path);
    if (!file.open("r")) {
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

  var result = {
    schemaVersion: 2,
    verifiedAt: new Date().toUTCString(),
    workingProject: app.project ? app.project.path : "",
    sequence: "",
    expectedSegments: 0,
    verifiedSegments: 0,
    reverseExpected: 0,
    reverseVerified: 0,
    sourceTrackIndexes: [],
    failures: [],
    projectExport: PROJECT_PATH,
    fcpXml: XML_PATH,
    success: false
  };

  try {
    var manifest = readJson(MANIFEST_PATH);
    var importManifest = readJson(IMPORT_PATH);
    var importById = {};
    for (var importIndex = 0; importIndex < importManifest.segments.length; importIndex++) {
      importById[importManifest.segments[importIndex].segmentId] =
        importManifest.segments[importIndex];
    }
    var sequence = app.project.activeSequence;
    if (!sequence || sequence.name !== "Paracosm Source Conform") {
      throw new Error("Paracosm Source Conform is not the active sequence.");
    }
    result.sequence = sequence.name;
    result.sequenceId = sequence.sequenceID;
    result.expectedSegments = manifest.segments.length;

    for (var trackIndex = 0; trackIndex < sequence.videoTracks.numTracks; trackIndex++) {
      if (
        String(sequence.videoTracks[trackIndex].name).indexOf(
          "TERMINAL SOURCE IMAGE SEQUENCES"
        ) === 0
      ) {
        result.sourceTrackIndexes.push(trackIndex);
      }
    }
    if (result.sourceTrackIndexes.length !== Number(importManifest.summary.lanes)) {
      throw new Error("The expected source conform tracks were not found.");
    }

    var foundIds = {};
    for (var segmentIndex = 0; segmentIndex < manifest.segments.length; segmentIndex++) {
      var segment = manifest.segments[segmentIndex];
      var importRecord = importById[segment.id];
      var track =
        sequence.videoTracks[
          result.sourceTrackIndexes[Number(importRecord.lane || 0)]
        ];
      var bestClip = null;
      var bestDistance = 999;
      for (var clipIndex = 0; clipIndex < track.clips.numItems; clipIndex++) {
        var clip = track.clips[clipIndex];
        var distance = Math.abs(
          clip.start.seconds - Number(segment.finalStart)
        );
        if (distance < bestDistance) {
          bestDistance = distance;
          bestClip = clip;
        }
      }
      if (!bestClip || bestDistance >= 0.03) {
        result.failures.push(segment.id + ": no clip at conformed start");
        continue;
      }
      var mediaPath = "";
      try {
        mediaPath = bestClip.projectItem.getMediaPath();
      } catch (ignoreMediaPath) {}
      if (mediaPath !== importRecord.importPath) {
        result.failures.push(segment.id + ": media path mismatch");
        continue;
      }
      bestClip.name = segment.id + " · " + bestClip.projectItem.name;
      foundIds[segment.id] = true;
      result.verifiedSegments++;
      if (importRecord.reversedMedia) {
        result.reverseExpected++;
        if (
          mediaPath.indexOf(
            ROOT + "/data/premiere/media/" + segment.id + "/"
          ) === 0
        ) {
          result.reverseVerified++;
        } else {
          result.failures.push(segment.id + ": reversed sequence is not archived");
        }
      }
    }

    var sourceClipCount = 0;
    for (var sourceIndex = 0; sourceIndex < result.sourceTrackIndexes.length; sourceIndex++) {
      sourceClipCount +=
        sequence.videoTracks[result.sourceTrackIndexes[sourceIndex]].clips.numItems;
    }
    result.sourceClipCount = sourceClipCount;
    if (sourceClipCount !== manifest.segments.length) {
      result.failures.push(
        "Source track clip count is " +
          sourceClipCount +
          ", expected " +
          manifest.segments.length
      );
    }

    if (new File(PROJECT_PATH).exists || new File(XML_PATH).exists) {
      throw new Error("VERIFIED conform export already exists; refusing to overwrite it.");
    }
    result.xmlExported = sequence.exportAsFinalCutProXML(XML_PATH);
    result.projectExported = sequence.exportAsProject(PROJECT_PATH);
    result.success =
      result.verifiedSegments === result.expectedSegments &&
      result.reverseVerified === result.reverseExpected &&
      result.failures.length === 0 &&
      result.xmlExported &&
      result.projectExported;
    writeJson(STATUS_PATH, result);
    return JSON.stringify(result, null, 2);
  } catch (error) {
    result.failures.push(String(error));
    try {
      writeJson(STATUS_PATH, result);
    } catch (ignoreWrite) {}
    return JSON.stringify(result, null, 2);
  }
})();
