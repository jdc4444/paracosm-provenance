/* Export the user-cleaned canonical conform and a lossless sequence inventory. */
(function () {
  var ROOT = "/Users/alphaone/Documents/Code/paracosm-provenance";
  var OUTPUT_DIR = ROOT + "/data/premiere";
  var EXPECTED_SEQUENCE = "Paracosm Conform Codex JD Clean";
  var TICKS_PER_SECOND = 254016000000;

  function pad(value, width) {
    var result = String(value);
    while (result.length < width) {
      result = "0" + result;
    }
    return result;
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

  function writeJson(path, value) {
    var file = new File(path);
    file.encoding = "UTF-8";
    if (!file.open("w")) {
      throw new Error("Cannot write " + path);
    }
    file.write(JSON.stringify(value, null, 2));
    file.close();
  }

  function timeValue(time) {
    if (!time) {
      return null;
    }
    var ticks = "";
    var seconds = null;
    try {
      ticks = String(time.ticks);
    } catch (ignoreTicks) {}
    try {
      seconds = Number(time.seconds);
    } catch (ignoreSeconds) {}
    return {
      ticks: ticks,
      seconds: seconds
    };
  }

  function projectItemType(item) {
    if (!item) {
      return "";
    }
    try {
      return String(item.type);
    } catch (ignoreType) {}
    return "";
  }

  function mediaPath(item) {
    if (!item || !item.getMediaPath) {
      return "";
    }
    try {
      return String(item.getMediaPath() || "");
    } catch (ignoreMediaPath) {}
    return "";
  }

  function itemMetadata(item) {
    if (!item) {
      return {};
    }
    var result = {
      name: String(item.name || ""),
      nodeId: String(item.nodeId || ""),
      type: projectItemType(item),
      mediaPath: mediaPath(item)
    };
    try {
      result.treePath = String(item.treePath || "");
    } catch (ignoreTreePath) {}
    try {
      result.startTime = timeValue(item.getStartTime());
    } catch (ignoreStartTime) {}
    try {
      var interpretation = item.getFootageInterpretation();
      result.footageInterpretation = interpretation || null;
    } catch (ignoreInterpretation) {}
    return result;
  }

  function componentInventory(clip) {
    var result = [];
    try {
      for (var componentIndex = 0; componentIndex < clip.components.numItems; componentIndex++) {
        var component = clip.components[componentIndex];
        result.push({
          displayName: String(component.displayName || ""),
          matchName: String(component.matchName || ""),
          enabled: component.properties && component.properties.numItems
            ? component.properties[0].getValue()
            : null
        });
      }
    } catch (ignoreComponents) {}
    return result;
  }

  function clipInventory(clip, trackIndex, clipIndex, mediaType) {
    var speed = null;
    var speedReversed = null;
    try {
      speed = Number(clip.getSpeed());
    } catch (ignoreSpeed) {}
    try {
      speedReversed = Boolean(clip.isSpeedReversed());
    } catch (ignoreReverse) {}
    return {
      trackIndex: trackIndex,
      clipIndex: clipIndex,
      mediaType: mediaType,
      name: String(clip.name || ""),
      nodeId: String(clip.nodeId || ""),
      start: timeValue(clip.start),
      end: timeValue(clip.end),
      inPoint: timeValue(clip.inPoint),
      outPoint: timeValue(clip.outPoint),
      duration: timeValue(clip.duration),
      speed: speed,
      speedReversed: speedReversed,
      projectItem: itemMetadata(clip.projectItem),
      components: mediaType === "video" ? componentInventory(clip) : []
    };
  }

  function trackInventory(track, trackIndex, mediaType) {
    var result = {
      trackIndex: trackIndex,
      name: String(track.name || ""),
      mediaType: mediaType,
      clips: []
    };
    try {
      result.isMuted = Boolean(track.isMuted());
    } catch (ignoreMuted) {}
    try {
      result.isLocked = Boolean(track.isLocked());
    } catch (ignoreLocked) {}
    for (var clipIndex = 0; clipIndex < track.clips.numItems; clipIndex++) {
      result.clips.push(
        clipInventory(track.clips[clipIndex], trackIndex, clipIndex, mediaType)
      );
    }
    return result;
  }

  var result = {
    schemaVersion: 1,
    exportedAt: new Date().toUTCString(),
    projectPath: app.project ? String(app.project.path || "") : "",
    expectedSequence: EXPECTED_SEQUENCE,
    success: false,
    errors: []
  };

  try {
    if (!app.project || !app.project.activeSequence) {
      throw new Error("No active Premiere sequence.");
    }
    var sequence = app.project.activeSequence;
    if (sequence.name !== EXPECTED_SEQUENCE) {
      throw new Error(
        'Expected active sequence "' +
          EXPECTED_SEQUENCE +
          '", got "' +
          sequence.name +
          '".'
      );
    }

    var stamp = timestamp();
    var stem =
      OUTPUT_DIR + "/Paracosm_Conform_Codex_JD_Clean_CANONICAL_" + stamp;
    result.sequence = {
      name: String(sequence.name),
      sequenceId: String(sequence.sequenceID || ""),
      timebaseTicksPerFrame: String(sequence.timebase || ""),
      ticksPerSecond: TICKS_PER_SECOND,
      zeroPoint: String(sequence.zeroPoint || ""),
      end: timeValue(sequence.end),
      videoTracks: [],
      audioTracks: []
    };
    try {
      result.sequence.settings = sequence.getSettings();
    } catch (ignoreSettings) {}

    for (
      var videoTrackIndex = 0;
      videoTrackIndex < sequence.videoTracks.numTracks;
      videoTrackIndex++
    ) {
      result.sequence.videoTracks.push(
        trackInventory(
          sequence.videoTracks[videoTrackIndex],
          videoTrackIndex,
          "video"
        )
      );
    }
    for (
      var audioTrackIndex = 0;
      audioTrackIndex < sequence.audioTracks.numTracks;
      audioTrackIndex++
    ) {
      result.sequence.audioTracks.push(
        trackInventory(
          sequence.audioTracks[audioTrackIndex],
          audioTrackIndex,
          "audio"
        )
      );
    }

    result.projectExport = stem + ".prproj";
    result.fcpXml = stem + ".xml";
    result.inventoryPath = stem + ".json";
    result.fcpXmlExported = Boolean(
      sequence.exportAsFinalCutProXML(result.fcpXml)
    );
    result.projectExported = Boolean(sequence.exportAsProject(result.projectExport));
    result.success = result.fcpXmlExported && result.projectExported;

    writeJson(result.inventoryPath, result);
    writeJson(OUTPUT_DIR + "/clean-conform-latest.json", result);
    return JSON.stringify(
      {
        success: result.success,
        sequence: result.sequence.name,
        videoTracks: result.sequence.videoTracks.length,
        audioTracks: result.sequence.audioTracks.length,
        inventoryPath: result.inventoryPath,
        fcpXml: result.fcpXml,
        projectExport: result.projectExport,
        errors: result.errors
      },
      null,
      2
    );
  } catch (error) {
    result.errors.push(String(error));
    try {
      writeJson(OUTPUT_DIR + "/clean-conform-latest.json", result);
    } catch (ignoreWriteError) {}
    return JSON.stringify(result, null, 2);
  }
})();
