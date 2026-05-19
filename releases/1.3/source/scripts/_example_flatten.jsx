// _example_flatten.jsx
// Example custom script for TA-F PS-BATCH Script Runner.
//
// How it works:
//   The launcher opens each PSD into Photoshop, then evals this file.
//   Your script should operate on `app.activeDocument`.
//   The launcher handles saving / closing based on the Output mode selected
//   in the GUI — DO NOT call save() or close() yourself.

(function () {
    if (!app.documents.length) {
        $.writeln("[example] no active document — skipping");
        return;
    }
    var doc = app.activeDocument;
    try {
        // Demo work: flatten all layers.
        doc.flatten();
        $.writeln("[example] flattened: " + doc.name);
    } catch (e) {
        $.writeln("[example] error on " + doc.name + ": " + e);
        throw e;  // let the wrapper catch it and log to the batch error list
    }
})();
