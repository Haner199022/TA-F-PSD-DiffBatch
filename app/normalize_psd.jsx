// =============================================================================
// normalize_psd.jsx — Generic batch PSD normalizer with ScriptUI dialog
//
// Reads the entire layer recipe (names, blend mode, opacity, visibility,
// stacking order, smart-filter chains) from a single REFERENCE PSD ("after")
// at runtime, then applies it to every PSD in a chosen folder. Works for any
// layer structure — nothing is hardcoded.
//
// Dialog flow:
//   1. Pick "After" reference PSD (required).
//   2. Pick "Before" PSD (optional, only used to preview the diff).
//   3. Pick batch source folder (required).
//   4. Click "Analyze" → preview the recipe + before/after diff.
//   5. Click "Run batch" → process every PSD; outputs go to <folder>/../_normalized/.
//
// Per-batch-PSD behavior:
//   - Match each reference layer by name in the batch PSD; align blend /
//     opacity / visibility.
//   - For smart-object layers in the reference, clear the batch layer's smart
//     filters and replay the reference's chain.
//   - Reorder all matched layers to match the reference's top→bottom order.
//   - Layers in the batch PSD missing from the reference are left untouched.
//   - Layer masks and smart-object contents are NEVER modified.
//
// Automation hook (for headless drivers like a Python launcher):
//   Set $.global.__NORMALIZE_AUTO__ = true and $.global.__NORMALIZE_CONFIG__ =
//   { referencePath, batchFolderPath, beforePath?, outFolderPath? } before
//   $.evalFile(this script). The dialog is skipped and the batch runs.
// =============================================================================

// ===== CONFIG =================================================================

// Optional default path. Used to pre-fill the dialog. Edit if your reference moved.
// \uXXXX escapes used so non-ASCII chars survive ExtendScript loading.
var DEFAULT_REFERENCE_PATH =
    "/Users/songyuhan/Library/Mobile Documents/iCloud~md~obsidian/Documents/Claude Code/Projects/TA-F/PS-BATCH/reserach/psd/H26_SET_01_SASS_&_SUNSHINE_INTL_PACKSHOT_RGB_after.psd";

// ===== LAYER + FILTER HELPERS =================================================

function findLayerByName(doc, name) {
    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === name) return doc.layers[i];
    }
    return null;
}

function readFilterChain(layer) {
    // Returns [{name, classID, descriptor}, ...]; empty if no smart filters.
    var ref = new ActionReference();
    ref.putIdentifier(stringIDToTypeID("layer"), layer.id);
    var desc = executeActionGet(ref);
    var soKey = stringIDToTypeID("smartObject");
    if (!desc.hasKey(soKey)) return [];
    var so = desc.getObjectValue(soKey);
    var fxKey = stringIDToTypeID("filterFX");
    if (!so.hasKey(fxKey)) return [];
    var list = so.getList(fxKey);
    var chain = [];
    var filterKey = stringIDToTypeID("filter");
    var nameKey = stringIDToTypeID("name");
    for (var i = 0; i < list.count; i++) {
        var item = list.getObjectValue(i);
        var name = item.hasKey(nameKey) ? item.getString(nameKey) : "(unnamed)";
        if (!item.hasKey(filterKey)) continue;
        var classID = item.getObjectType(filterKey);
        var filterDesc = item.getObjectValue(filterKey);
        chain.push({ name: name, classID: classID, descriptor: filterDesc });
    }
    return chain;
}

function clearSmartFilters() {
    try {
        var idDlt = charIDToTypeID("Dlt ");
        var d = new ActionDescriptor();
        var r = new ActionReference();
        r.putClass(stringIDToTypeID("filterFX"));
        d.putReference(charIDToTypeID("null"), r);
        executeAction(idDlt, d, DialogModes.NO);
        return true;
    } catch (e) { return false; }
}

function applyChain(doc, layer, chain, log) {
    doc.activeLayer = layer;
    clearSmartFilters();
    for (var i = 0; i < chain.length; i++) {
        try {
            executeAction(chain[i].classID, chain[i].descriptor, DialogModes.NO);
        } catch (e) {
            log.push("    ! apply '" + chain[i].name + "' on " + layer.name + ": " + e);
        }
    }
}

// ===== RECIPE EXTRACTION ======================================================

function _readLayerDescriptor(layer) {
    var ref = new ActionReference();
    ref.putIdentifier(stringIDToTypeID("layer"), layer.id);
    return executeActionGet(ref);
}

function _hasUserMask(layer) {
    try {
        var d = _readLayerDescriptor(layer);
        var k = stringIDToTypeID("hasUserMask");
        return d.hasKey(k) && d.getBoolean(k);
    } catch (e) { return false; }
}

function _activateMaskChannel() {
    var ref = new ActionReference();
    ref.putEnumerated(charIDToTypeID("Chnl"), charIDToTypeID("Chnl"), charIDToTypeID("Msk "));
    var desc = new ActionDescriptor();
    desc.putReference(charIDToTypeID("null"), ref);
    desc.putBoolean(charIDToTypeID("MkVs"), false);
    executeAction(charIDToTypeID("slct"), desc, DialogModes.NO);
}

function _activateRGBComposite() {
    var ref = new ActionReference();
    ref.putEnumerated(charIDToTypeID("Chnl"), charIDToTypeID("Chnl"), charIDToTypeID("RGB "));
    var desc = new ActionDescriptor();
    desc.putReference(charIDToTypeID("null"), ref);
    executeAction(charIDToTypeID("slct"), desc, DialogModes.NO);
}

function _addLayerMaskRevealAll() {
    // Canonical "Add Layer Mask → Reveal All" via Action Manager.
    var desc = new ActionDescriptor();
    desc.putClass(charIDToTypeID("Nw  "), charIDToTypeID("Chnl"));
    var ref = new ActionReference();
    ref.putEnumerated(charIDToTypeID("Chnl"), charIDToTypeID("Chnl"), charIDToTypeID("Msk "));
    desc.putReference(charIDToTypeID("At  "), ref);
    desc.putEnumerated(charIDToTypeID("Usng"), charIDToTypeID("UsrM"), charIDToTypeID("RvlA"));
    executeAction(charIDToTypeID("Mk  "), desc, DialogModes.NO);
}

function _findLayerById(doc, id) {
    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].id === id) return doc.layers[i];
    }
    return null;
}

function _isAovName(name) {
    return name && name.toLowerCase().indexOf("aov") >= 0;
}

function copyMaskBetweenDocs(srcDoc, srcLayer, dstDoc, dstLayer, log) {
    // Cross-doc mask transfer via Apply Image — avoids the clipboard / paste
    // path which creates new layers instead of writing to the mask channel.
    // Returns "copied" | "no-src" | "error". If src has no mask, leave dst
    // alone (per spec). Both docs must share canvas dimensions.

    // 1. Read src mask presence (must be done with src as active doc).
    app.activeDocument = srcDoc;
    srcDoc.activeLayer = srcLayer;
    if (!_hasUserMask(srcLayer)) return "no-src";

    // 2. Switch to dst; ensure dst has a layer mask.
    app.activeDocument = dstDoc;
    dstDoc.activeLayer = dstLayer;
    if (!_hasUserMask(dstLayer)) {
        try { _addLayerMaskRevealAll(); }
        catch (e) { log.push("    ! add mask on dst: " + e); return "error"; }
    }

    // 3. Activate dst's mask channel as the Apply-Image target.
    try { _activateMaskChannel(); }
    catch (e) { log.push("    ! activate dst mask: " + e); return "error"; }

    // 4. Apply Image: source = src layer's user mask channel in srcDoc.
    try {
        var withDesc = new ActionDescriptor();
        var srcRef = new ActionReference();
        srcRef.putEnumerated(charIDToTypeID("Chnl"), charIDToTypeID("Chnl"), charIDToTypeID("Msk "));
        srcRef.putIdentifier(stringIDToTypeID("layer"), srcLayer.id);
        srcRef.putName(charIDToTypeID("Dcmn"), srcDoc.name);
        withDesc.putReference(charIDToTypeID("T   "), srcRef);
        withDesc.putBoolean(charIDToTypeID("Invr"), false);
        withDesc.putEnumerated(charIDToTypeID("Clcl"), charIDToTypeID("Clcn"), charIDToTypeID("Nrml"));

        var desc = new ActionDescriptor();
        desc.putObject(charIDToTypeID("With"), charIDToTypeID("Clcl"), withDesc);
        executeAction(charIDToTypeID("AppI"), desc, DialogModes.NO);
    } catch (e) {
        log.push("    ! Apply Image failed for '" + dstLayer.name + "': " + e);
        try { _activateRGBComposite(); } catch (e2) {}
        return "error";
    }

    try { _activateRGBComposite(); } catch (e) {}
    return "copied";
}

function _readAdjustmentDescriptor(layer) {
    // For fill / adjustment layers, the 'adjustment' key holds a list whose
    // first item carries the descriptor (color, curve points, etc.). We
    // capture the inner descriptor + its class so we can replay 'Make' later.
    var desc;
    try { desc = _readLayerDescriptor(layer); }
    catch (e) { return null; }
    var adjKey = stringIDToTypeID("adjustment");
    if (!desc.hasKey(adjKey)) return null;
    var t = desc.getType(adjKey);
    if (t !== DescValueType.LISTTYPE) return null;
    var list = desc.getList(adjKey);
    if (list.count === 0) return null;
    return {
        classID:    list.getObjectType(0),
        classStringID: typeIDToStringID(list.getObjectType(0)),
        descriptor: list.getObjectValue(0)
    };
}

function extractRecipe(refDoc) {
    // Walk top-down (visual). ExtendScript's doc.layers is bottom→top, so
    // iterate backwards. recipe[0] = visual top of stack.
    var recipe = [];
    for (var i = refDoc.layers.length - 1; i >= 0; i--) {
        var lyr = refDoc.layers[i];
        var kindStr = String(lyr.kind);  // e.g. "LayerKind.SMARTOBJECT"
        var entry = {
            name:          lyr.name,
            blendMode:     lyr.blendMode,
            opacity:       lyr.opacity,
            visible:       lyr.visible,
            kind:          kindStr,
            isSmartObject: (lyr.kind === LayerKind.SMARTOBJECT),
            isSolidFill:   (lyr.kind === LayerKind.SOLIDFILL),
            refLayerId:    lyr.id  // ID in the reference doc — used for mask copy
        };
        entry.filterChain         = entry.isSmartObject ? readFilterChain(lyr) : null;
        // Capture adjustment/fill descriptor for fill+adjustment kinds (used to
        // recreate the layer in batch PSDs that don't have it).
        if (!entry.isSmartObject) {
            entry.adjustment = _readAdjustmentDescriptor(lyr);
        } else {
            entry.adjustment = null;
        }
        recipe.push(entry);
    }
    return recipe;
}

function summarizeRecipe(recipe) {
    var lines = [];
    lines.push(recipe.length + " layers (top → bottom):");
    for (var i = 0; i < recipe.length; i++) {
        var e = recipe[i];
        var fc = e.filterChain ? (" filters=" + e.filterChain.length) : "";
        var adj = e.adjustment ? (" adj=" + e.adjustment.classStringID) : "";
        lines.push("  [" + i + "] " + e.name +
                   " | blend=" + e.blendMode + " | op=" + e.opacity +
                   " | vis=" + e.visible + (e.isSmartObject ? " | SO" : "") + fc + adj);
    }
    return lines;
}

// ===== DIFF COMPUTATION =======================================================

function blendModeStr(bm) {
    // Normalize for diff display (BlendMode.X → "X")
    var s = String(bm);
    var dot = s.indexOf(".");
    return dot >= 0 ? s.substring(dot + 1) : s;
}

function filterChainNames(chain) {
    if (!chain) return "(non-SO)";
    if (chain.length === 0) return "(no filters)";
    var names = [];
    for (var i = 0; i < chain.length; i++) names.push(chain[i].name);
    return names.join(" → ");
}

function diffRecipes(beforeRecipe, afterRecipe) {
    // Returns a list of human-readable diff lines.
    // Handles duplicate names by maintaining per-name BUCKETS of {entry, idx}
    // and consuming them in iteration order during matching.
    var lines = [];

    function bucketize(recipe) {
        var b = {};
        for (var i = 0; i < recipe.length; i++) {
            var nm = recipe[i].name;
            if (!b[nm]) b[nm] = [];
            b[nm].push({ entry: recipe[i], idx: i });
        }
        return b;
    }

    var beforeBuckets = bucketize(beforeRecipe);
    var afterBuckets  = bucketize(afterRecipe);

    // Names ADDED in after (more after copies than before)
    for (var na in afterBuckets) if (afterBuckets.hasOwnProperty(na)) {
        var afterCount  = afterBuckets[na].length;
        var beforeCount = beforeBuckets[na] ? beforeBuckets[na].length : 0;
        for (var x = 0; x < afterCount - beforeCount; x++) {
            lines.push("+ ADDED layer: " + na + (afterCount > 1 ? " (#" + (beforeCount + x + 1) + ")" : ""));
        }
    }
    // Names REMOVED in after (fewer after copies than before)
    for (var nb in beforeBuckets) if (beforeBuckets.hasOwnProperty(nb)) {
        var beforeCount2 = beforeBuckets[nb].length;
        var afterCount2  = afterBuckets[nb] ? afterBuckets[nb].length : 0;
        for (var y = 0; y < beforeCount2 - afterCount2; y++) {
            lines.push("- REMOVED layer: " + nb);
        }
    }

    // Per-layer diffs: walk after top→bottom, consume same-named beforeBucket
    // entries in the order they appeared in before.
    var beforeConsumed = {}; // name → next index to consume from beforeBuckets[name]
    for (var k = 0; k < afterRecipe.length; k++) {
        var a = afterRecipe[k];
        var bucket = beforeBuckets[a.name];
        if (!bucket) continue;
        var ci = beforeConsumed[a.name] || 0;
        if (ci >= bucket.length) continue; // no remaining before instance
        var bPair = bucket[ci];
        beforeConsumed[a.name] = ci + 1;

        var b = bPair.entry, bIdx = bPair.idx;
        var changes = [];
        if (blendModeStr(a.blendMode) !== blendModeStr(b.blendMode)) {
            changes.push("blend " + blendModeStr(b.blendMode) + " → " + blendModeStr(a.blendMode));
        }
        if (a.opacity !== b.opacity)  changes.push("opacity " + b.opacity + "% → " + a.opacity + "%");
        if (a.visible !== b.visible)  changes.push("visible " + b.visible + " → " + a.visible);
        if (k !== bIdx)               changes.push("position [" + bIdx + "] → [" + k + "]");
        var aChain = filterChainNames(a.filterChain);
        var bChain = filterChainNames(b.filterChain);
        if (aChain !== bChain)        changes.push("filters: " + bChain + " ⇒ " + aChain);
        if (changes.length) {
            lines.push("• " + a.name + ":");
            for (var c = 0; c < changes.length; c++) lines.push("    " + changes[c]);
        }
    }

    if (lines.length === 0) lines.push("(no differences)");
    return lines;
}

// ===== APPLY: recipe → batch PSD ==============================================

function _createSolidFillLayer(doc, entry, log) {
    // Replay the captured solidColorLayer (or any 'adjustment[0]' descriptor)
    // via the Make action.
    var adj = entry.adjustment;
    if (!adj) { log.push("    ! cannot create '" + entry.name + "': no adjustment descriptor"); return null; }

    var makeDesc = new ActionDescriptor();
    var ref = new ActionReference();
    ref.putClass(stringIDToTypeID("contentLayer"));
    makeDesc.putReference(stringIDToTypeID("null"), ref);

    var contentDesc = new ActionDescriptor();
    contentDesc.putObject(stringIDToTypeID("type"), adj.classID, adj.descriptor);
    makeDesc.putObject(stringIDToTypeID("using"), stringIDToTypeID("contentLayer"), contentDesc);

    try {
        executeAction(charIDToTypeID("Mk  "), makeDesc, DialogModes.NO);
    } catch (e) {
        log.push("    ! Make contentLayer failed for '" + entry.name + "': " + e);
        return null;
    }
    var newLayer = doc.activeLayer;
    try { newLayer.name = entry.name; } catch (e) {}
    return newLayer;
}

function _duplicateExistingSmartObject(entry, pairs, log) {
    // Find any already-paired SMARTOBJECT in pairs whose name matches this
    // entry, and duplicate it. The duplicate inherits the source's content
    // (same embedded PSB) but its filter chain will be cleared+rebuilt later.
    for (var i = 0; i < pairs.length; i++) {
        var p = pairs[i];
        if (p.layer.name === entry.name && p.layer.kind === LayerKind.SMARTOBJECT) {
            try {
                var dup = p.layer.duplicate();
                try { dup.name = entry.name; } catch (e2) {}
                return dup;
            } catch (e) {
                log.push("    ! duplicate failed for '" + entry.name + "': " + e);
                return null;
            }
        }
    }
    return null;
}

function _createLayerFromEntry(doc, entry, pairs, log) {
    // Returns the new Layer or null if creation isn't supported / failed.
    if (entry.isSolidFill && entry.adjustment) {
        return _createSolidFillLayer(doc, entry, log);
    }
    if (entry.isSmartObject) {
        return _duplicateExistingSmartObject(entry, pairs, log);
    }
    // Other kinds (curves, hue/sat, gradient fill, etc.) with adjustment descriptor:
    // try the same Make-contentLayer path. Most fill+adjustment classes accept it.
    if (entry.adjustment) {
        return _createSolidFillLayer(doc, entry, log);
    }
    log.push("    ! cannot create '" + entry.name + "' (kind=" + entry.kind + "): unsupported");
    return null;
}

function applyRecipeToDoc(doc, recipe, log, refDoc) {
    // Phase 1: build a map of available batch layers by name (preserves the
    // bottom→top iteration order PS gives us — popping gives the first one
    // visually from the bottom; for our reorder step that's fine since we
    // overwrite positions afterward).
    var byName = {};
    for (var i = 0; i < doc.layers.length; i++) {
        var lyr = doc.layers[i];
        if (!byName[lyr.name]) byName[lyr.name] = [];
        byName[lyr.name].push(lyr);
    }

    // Phase 2: walk recipe top→bottom; match same-named batch layer or create.
    var pairs = [];   // [{entry, layer, created}, ...]
    var createdCount = 0, matchedCount = 0;
    for (var r = 0; r < recipe.length; r++) {
        var entry = recipe[r];
        var bucket = byName[entry.name];
        if (bucket && bucket.length > 0) {
            pairs.push({ entry: entry, layer: bucket.shift(), created: false });
            matchedCount++;
        } else {
            var newLyr = _createLayerFromEntry(doc, entry, pairs, log);
            if (newLyr) {
                pairs.push({ entry: entry, layer: newLyr, created: true });
                createdCount++;
                log.push("    + created '" + entry.name + "' (" + entry.kind + ")");
            } else {
                log.push("    ! skipped '" + entry.name + "' — no batch match and creation failed");
            }
        }
    }

    // Phase 3: apply blend/opacity/visible + filter chain for every pair
    for (var p = 0; p < pairs.length; p++) {
        var lyr = pairs[p].layer;
        var ent = pairs[p].entry;
        try { lyr.blendMode = ent.blendMode; } catch (e) { log.push("    ! blend " + ent.name + ": " + e); }
        try { lyr.opacity   = ent.opacity; }   catch (e) { log.push("    ! opacity " + ent.name + ": " + e); }
        try { lyr.visible   = ent.visible; }   catch (e) { log.push("    ! visible " + ent.name + ": " + e); }
        if (ent.isSmartObject && lyr.kind === LayerKind.SMARTOBJECT) {
            applyChain(doc, lyr, ent.filterChain, log);
        }
    }

    // Phase 4: reorder. PLACEATEND = visual top, PLACEBEFORE(X) = directly below X.
    if (pairs.length) {
        try { pairs[0].layer.move(doc, ElementPlacement.PLACEATEND); }
        catch (e) { log.push("    ! move-to-top: " + e); }
        for (var j = 1; j < pairs.length; j++) {
            try { pairs[j].layer.move(pairs[j - 1].layer, ElementPlacement.PLACEBEFORE); }
            catch (e) { log.push("    ! reorder " + pairs[j].entry.name + ": " + e); }
        }
    }

    // Phase 5: mask copy for non-AOV layers.
    //   AOV layers     → keep batch's original mask untouched
    //   non-AOV layers → if after has a mask on that layer, copy it; else leave batch alone
    var maskCopied = 0, maskSkippedAov = 0, maskNoSrc = 0, maskErr = 0;
    if (refDoc) {
        for (var m = 0; m < pairs.length; m++) {
            var pe = pairs[m];
            if (_isAovName(pe.entry.name)) { maskSkippedAov++; continue; }
            var refLyr = _findLayerById(refDoc, pe.entry.refLayerId);
            if (!refLyr) {
                log.push("    ! ref layer not found by id for '" + pe.entry.name + "'");
                continue;
            }
            var res = copyMaskBetweenDocs(refDoc, refLyr, doc, pe.layer, log);
            if      (res === "copied") maskCopied++;
            else if (res === "no-src") maskNoSrc++;
            else                       maskErr++;
        }
        // Make batch the active doc again (mask copy switched activeDocument)
        try { app.activeDocument = doc; } catch (e) {}
    }

    log.push("    [match=" + matchedCount + " create=" + createdCount + " of " + recipe.length + "]");
    log.push("    [masks: copied=" + maskCopied + " aov-skip=" + maskSkippedAov + " no-src=" + maskNoSrc + " err=" + maskErr + "]");
    return pairs.length;
}

function processOne(file, outFolder, recipe, log, refDoc) {
    var doc;
    try { doc = app.open(file); }
    catch (e) { log.push("[ERR] open " + file.name + ": " + e); return false; }

    var n = applyRecipeToDoc(doc, recipe, log, refDoc);
    log.push("    matched " + n + "/" + recipe.length + " layers");

    var outFile = new File(outFolder.fsName + "/" + file.name);
    var saveOpts = new PhotoshopSaveOptions();
    saveOpts.embedColorProfile     = true;
    saveOpts.alphaChannels         = true;
    saveOpts.layers                = true;
    saveOpts.spotColors            = true;
    saveOpts.annotations           = true;
    saveOpts.maximizeCompatibility = true;
    try { doc.saveAs(outFile, saveOpts, true /* asCopy */, Extension.LOWERCASE); }
    catch (e) { log.push("[ERR] save " + file.name + ": " + e); doc.close(SaveOptions.DONOTSAVECHANGES); return false; }

    doc.close(SaveOptions.DONOTSAVECHANGES);
    return true;
}

// ===== CORE: open ref → extract → process folder ==============================

function runBatch(cfg, onProgress, onLog) {
    // cfg: { referencePath, batchFolderPath, outFolderPath? }
    // onProgress(msg): called between major steps for UI updates (optional)
    // onLog(line): called per log line (optional)
    var log = [];

    var refFile = new File(cfg.referencePath);
    if (!refFile.exists) throw new Error("Reference file not found: " + cfg.referencePath);

    var srcFolder = new Folder(cfg.batchFolderPath);
    if (!srcFolder.exists) throw new Error("Source folder not found: " + cfg.batchFolderPath);

    var refFsName = refFile.fsName;
    var files = srcFolder.getFiles(function (f) {
        if (!(f instanceof File)) return false;
        if (!/\.psd$/i.test(f.name)) return false;
        if (f.fsName === refFsName) return false;
        return true;
    });
    if (!files || files.length === 0) throw new Error("No .psd files found in: " + srcFolder.fsName);

    var outFolderPath = cfg.outFolderPath || (srcFolder.parent.fsName + "/_normalized");
    var outFolder = new Folder(outFolderPath);
    if (!outFolder.exists) outFolder.create();

    // Open log file in append mode so external tailers (e.g. Python launcher)
    // see progress in real time. Override log.push so EVERY caller's push also
    // flushes to disk — including the inner functions that get the `log` array
    // passed in (applyRecipeToDoc, applyChain, processOne, etc.).
    var logFile = new File(outFolder.fsName + "/normalize_log.txt");
    logFile.encoding = "UTF-8";
    try { logFile.open("w"); logFile.write(""); logFile.close(); } catch (e) {}
    var _origPush = log.push;
    log.push = function (line) {
        _origPush.call(log, line);
        try {
            logFile.open("a");
            logFile.write(line + "\n");
            logFile.close();
        } catch (e) {}
        if (onLog) onLog(line);
    };
    function pushLog(line) { log.push(line); }  // backwards-compat alias
    function progress(msg) { if (onProgress) onProgress(msg); }

    var origDialogs = app.displayDialogs;
    app.displayDialogs = DialogModes.NO;
    var t0 = (new Date()).getTime();

    // Read reference recipe; KEEP refDoc OPEN for mask copying during batch.
    progress("Reading reference...");
    var refDoc, recipe;
    try {
        refDoc = app.open(refFile);
        pushLog("[ref] opened " + refFile.name);
        recipe = extractRecipe(refDoc);
        var summary = summarizeRecipe(recipe);
        for (var s = 0; s < summary.length; s++) pushLog(summary[s]);
    } catch (e) {
        try { if (refDoc) refDoc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {}
        app.displayDialogs = origDialogs;
        throw e;
    }

    // Cancel marker — Python launcher creates this file when user clicks CANCEL.
    // We check between each PSD; ExtendScript File.exists hits the FS every call.
    var cancelMarker = new File(outFolder.fsName + "/.cancel");
    var cancelled = false;

    var ok = 0, fail = 0;
    try {
        for (var i = 0; i < files.length; i++) {
            if (cancelMarker.exists) {
                pushLog("--- CANCELLED at " + i + "/" + files.length + " ---");
                cancelled = true;
                break;
            }
            progress("Processing " + (i + 1) + "/" + files.length + ": " + files[i].name);
            pushLog("--- (" + (i + 1) + "/" + files.length + ") " + files[i].name + " ---");
            if (processOne(files[i], outFolder, recipe, log, refDoc)) ok++; else fail++;
        }
    } finally {
        try { refDoc.close(SaveOptions.DONOTSAVECHANGES); } catch (e) {}
    }

    app.displayDialogs = origDialogs;
    var elapsed = ((new Date()).getTime() - t0) / 1000;
    pushLog("");
    if (cancelled) {
        pushLog("=== CANCELLED after " + elapsed.toFixed(1) + "s — " + ok + " ok, " + fail + " failed, " + (files.length - ok - fail) + " skipped ===");
    } else {
        pushLog("=== DONE in " + elapsed.toFixed(1) + "s — " + ok + " ok, " + fail + " failed ===");
    }

    return { ok: ok, fail: fail, cancelled: cancelled, total: files.length, elapsed: elapsed, outFolder: outFolder.fsName, logFile: logFile.fsName };
}

// ===== ANALYZE: read ref + before, return summary + diff ======================

function analyze(cfg) {
    // cfg: { referencePath, beforePath? } — beforePath optional
    // Returns { recipeSummary: [lines], diff: [lines] | null }
    var origDialogs = app.displayDialogs;
    app.displayDialogs = DialogModes.NO;

    var afterDoc, beforeDoc;
    var afterRecipe, beforeRecipe = null;
    try {
        afterDoc = app.open(new File(cfg.referencePath));
        afterRecipe = extractRecipe(afterDoc);
        afterDoc.close(SaveOptions.DONOTSAVECHANGES);
        afterDoc = null;

        if (cfg.beforePath) {
            var bf = new File(cfg.beforePath);
            if (bf.exists) {
                beforeDoc = app.open(bf);
                beforeRecipe = extractRecipe(beforeDoc);
                beforeDoc.close(SaveOptions.DONOTSAVECHANGES);
                beforeDoc = null;
            }
        }
    } catch (e) {
        try { if (afterDoc)  afterDoc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {}
        try { if (beforeDoc) beforeDoc.close(SaveOptions.DONOTSAVECHANGES); } catch (e3) {}
        app.displayDialogs = origDialogs;
        throw e;
    }

    app.displayDialogs = origDialogs;

    return {
        recipeSummary: summarizeRecipe(afterRecipe),
        diff: beforeRecipe ? diffRecipes(beforeRecipe, afterRecipe) : null
    };
}

// ===== UI: ScriptUI dialog ====================================================

function buildDialog() {
    var w = new Window("dialog", "TA-F PSD DiffBatch");
    w.alignChildren = "fill";
    w.spacing = 10;
    w.margins = 16;

    function pickRow(labelText, isFolder) {
        var g = w.add("group");
        g.alignChildren = "center";
        g.add("statictext", undefined, labelText).preferredSize.width = 130;
        var et = g.add("edittext", undefined, "");
        et.preferredSize.width = 480;
        var btn = g.add("button", undefined, "Browse...");
        btn.preferredSize.width = 90;
        btn.onClick = function () {
            var picked = isFolder
                ? Folder.selectDialog("Select " + labelText)
                : File.openDialog("Select " + labelText, "*.psd");
            if (picked) et.text = picked.fsName;
        };
        return et;
    }

    var afterField  = pickRow("After (reference):", false);
    var beforeField = pickRow("Before (optional):", false);
    var folderField = pickRow("Batch folder:", true);
    var outField    = pickRow("Output folder (optional):", true);

    afterField.text = DEFAULT_REFERENCE_PATH;

    // Output panel
    var outPanel = w.add("panel", undefined, "Output");
    outPanel.alignChildren = "fill";
    outPanel.margins = 8;
    var status = outPanel.add("statictext", undefined, "Ready.");
    status.preferredSize.width = 720;
    var outText = outPanel.add("edittext", undefined, "", { multiline: true, scrolling: true, readonly: true });
    outText.preferredSize = [720, 280];

    // Buttons
    var btnRow = w.add("group");
    btnRow.alignment = "right";
    var analyzeBtn = btnRow.add("button", undefined, "Analyze");
    var runBtn     = btnRow.add("button", undefined, "Run batch");
    var closeBtn   = btnRow.add("button", undefined, "Close", { name: "cancel" });

    function setStatus(s) { status.text = s; w.update(); }
    function appendOut(line) {
        outText.text = outText.text + (outText.text ? "\n" : "") + line;
        w.update();
    }
    function clearOut() { outText.text = ""; w.update(); }

    analyzeBtn.onClick = function () {
        if (!afterField.text) { alert("Please pick the After (reference) PSD."); return; }
        clearOut();
        setStatus("Analyzing...");
        try {
            var res = analyze({ referencePath: afterField.text, beforePath: beforeField.text || null });
            appendOut("=== Recipe (from after) ===");
            for (var i = 0; i < res.recipeSummary.length; i++) appendOut(res.recipeSummary[i]);
            if (res.diff) {
                appendOut("");
                appendOut("=== Diff (before → after) ===");
                for (var j = 0; j < res.diff.length; j++) appendOut(res.diff[j]);
            } else {
                appendOut("");
                appendOut("(no before file provided — diff skipped)");
            }
            setStatus("Analyze complete.");
        } catch (e) {
            setStatus("Analyze failed.");
            appendOut("ERROR: " + e);
        }
    };

    runBtn.onClick = function () {
        if (!afterField.text) { alert("Please pick the After (reference) PSD."); return; }
        if (!folderField.text) { alert("Please pick the batch folder."); return; }
        clearOut();
        setStatus("Running batch...");
        try {
            var runCfg = {
                referencePath:   afterField.text,
                batchFolderPath: folderField.text
            };
            if (outField.text) runCfg.outFolderPath = outField.text;
            var result = runBatch(
                runCfg,
                function (msg) { setStatus(msg); },
                function (line) { appendOut(line); }
            );
            setStatus("Done: " + result.ok + " ok, " + result.fail + " failed in " + result.elapsed.toFixed(1) + "s");
            appendOut("");
            appendOut("Output folder: " + result.outFolder);
            appendOut("Log file:      " + result.logFile);
        } catch (e) {
            setStatus("Batch failed.");
            appendOut("ERROR: " + e);
        }
    };

    closeBtn.onClick = function () { w.close(0); };

    return w;
}

// ===== MAIN ===================================================================

// JSON-ish writer for automation results (avoids depending on JSON library).
function _writeAutoResult(path, obj) {
    function esc(s) { return String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n").replace(/\r/g, "\\r"); }
    function emit(v) {
        if (v === null || typeof v === "undefined") return "null";
        if (typeof v === "boolean") return v ? "true" : "false";
        if (typeof v === "number") return String(v);
        if (typeof v === "string") return '"' + esc(v) + '"';
        if (v instanceof Array) {
            var parts = [];
            for (var i = 0; i < v.length; i++) parts.push(emit(v[i]));
            return "[" + parts.join(",") + "]";
        }
        // object
        var ps = [];
        for (var k in v) if (v.hasOwnProperty(k)) ps.push('"' + esc(k) + '":' + emit(v[k]));
        return "{" + ps.join(",") + "}";
    }
    var f = new File(path);
    f.encoding = "UTF-8"; f.open("w"); f.write(emit(obj)); f.close();
}

function main() {
    // Automation: ANALYZE — writes recipe + diff to JSON file, then exits.
    if ($.global.__ANALYZE_AUTO__ && $.global.__ANALYZE_CONFIG__) {
        var acfg = $.global.__ANALYZE_CONFIG__;
        try {
            var aRes = analyze(acfg);
            _writeAutoResult(acfg.outputPath || "/tmp/_normalize_analyze.json",
                             { ok: true, recipeSummary: aRes.recipeSummary, diff: aRes.diff });
        } catch (e) {
            _writeAutoResult(acfg.outputPath || "/tmp/_normalize_analyze.json",
                             { ok: false, error: String(e) });
        }
        return;
    }

    // Automation: BATCH — runs the batch, writes result + log path to JSON.
    if ($.global.__NORMALIZE_AUTO__ && $.global.__NORMALIZE_CONFIG__) {
        var cfg = $.global.__NORMALIZE_CONFIG__;
        try {
            var result = runBatch(cfg);
            $.global.__NORMALIZE_RESULT__ = result;
            if (cfg.outputPath) _writeAutoResult(cfg.outputPath, { ok: true, result: result });
        } catch (e) {
            $.global.__NORMALIZE_ERROR__ = String(e);
            if (cfg.outputPath) _writeAutoResult(cfg.outputPath, { ok: false, error: String(e) });
        }
        return;
    }

    // Interactive mode: show dialog
    var w = buildDialog();
    w.show();
}

main();
