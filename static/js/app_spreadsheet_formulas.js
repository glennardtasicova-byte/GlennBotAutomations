// ============================================================================
// GLENNBOT SPREADSHEET ENGINE:
// 1. Complete Excel / MS365 Formula Evaluator (All 10 Categories, Excluding IMAGE)
// 2. Interactive Formula Point-and-Click / Drag / Ctrl+Click Cell & Range Picker
// 3. F4 Shortcut Key ($A$1 -> A$1 -> $A1 -> A1) Absolute/Relative Reference Toggle
// ============================================================================

(function () {
    'use strict';

    const BLOCKED_IMAGE_FORMULAS = new Set([
        'IMAGE', 'SPARKLINE', 'IMPORTIMAGE', 'EMBEDIMAGE', 'WEBIMAGE', 'PICTURE'
    ]);

    // --- Interactive Formula Point-Mode State ---
    window.ssFormulaPointState = {
        activeInputId: null,       // 'ss-formula-bar-input' or 'ss-cell-A1'
        formulaCellCoord: null,    // Coordinate of the cell whose formula is being edited
        tokenStart: null,          // Start index in formula string of the currently pointed reference token
        tokenEnd: null,            // End index in formula string of the currently pointed reference token
        anchorCoord: null,         // Start cell coordinate for drag/Shift-click range selection in formula
        isDraggingRef: false       // True while mouse is held down dragging a formula range
    };

    window.ssResetFormulaPointToken = function () {
        window.ssFormulaPointState.tokenStart = null;
        window.ssFormulaPointState.tokenEnd = null;
        window.ssFormulaPointState.anchorCoord = null;
        window.ssFormulaPointState.isDraggingRef = false;
    };

    // Determine if the user is actively editing a formula (starts with '=') and return the target input element
    window.ssGetActiveFormulaEditorInfo = function () {
        const fBar = document.getElementById('ss-formula-bar-input');
        const editCoord = typeof ssEditingCellCoord !== 'undefined' ? ssEditingCellCoord : null;
        const cellInput = editCoord ? document.getElementById(`ss-cell-${editCoord}`) : null;

        const activeEl = document.activeElement;
        if (activeEl === fBar && String(fBar.value || '').trimStart().startsWith('=')) {
            window.ssFormulaPointState.activeInputId = 'ss-formula-bar-input';
            window.ssFormulaPointState.formulaCellCoord = typeof activeCellCoord !== 'undefined' ? activeCellCoord : 'A1';
            return { inputEl: fBar, cellCoord: window.ssFormulaPointState.formulaCellCoord, isFormulaBar: true };
        }
        if (cellInput && (activeEl === cellInput || editCoord) && String(cellInput.value || '').trimStart().startsWith('=')) {
            window.ssFormulaPointState.activeInputId = cellInput.id;
            window.ssFormulaPointState.formulaCellCoord = editCoord;
            return { inputEl: cellInput, cellCoord: editCoord, isFormulaBar: false };
        }
        if (window.ssFormulaPointState.activeInputId) {
            const rememberedEl = document.getElementById(window.ssFormulaPointState.activeInputId);
            if (rememberedEl && String(rememberedEl.value || '').trimStart().startsWith('=')) {
                return {
                    inputEl: rememberedEl,
                    cellCoord: window.ssFormulaPointState.formulaCellCoord || (typeof activeCellCoord !== 'undefined' ? activeCellCoord : 'A1'),
                    isFormulaBar: rememberedEl.id === 'ss-formula-bar-input'
                };
            }
        }
        // Fallback: if Formula Bar currently contains an incomplete formula expression (e.g. ends with '(', ',', '+', '=')
        if (fBar && String(fBar.value || '').trimStart().startsWith('=')) {
            const trimmed = String(fBar.value || '').trimEnd();
            const lastCh = trimmed[trimmed.length - 1] || '';
            if (['=', '(', ',', ';', '+', '-', '*', '/', '^', '&', '<', '>', ':'].includes(lastCh)) {
                window.ssFormulaPointState.activeInputId = 'ss-formula-bar-input';
                window.ssFormulaPointState.formulaCellCoord = typeof activeCellCoord !== 'undefined' ? activeCellCoord : 'A1';
                return { inputEl: fBar, cellCoord: window.ssFormulaPointState.formulaCellCoord, isFormulaBar: true };
            }
        }
        return null;
    };

    // Check if the formula editor is in a state where clicking/dragging cells should insert a cell reference
    window.ssShouldInterceptGridForFormulaPointing = function () {
        const info = window.ssGetActiveFormulaEditorInfo();
        if (!info || !info.inputEl) return false;
        const val = String(info.inputEl.value || '');
        if (!val.trimStart().startsWith('=')) return false;

        // If we already have an active pointed token, clicking/dragging updates or appends to it
        if (window.ssFormulaPointState.tokenStart !== null && window.ssFormulaPointState.tokenEnd !== null) {
            return true;
        }

        const caret = typeof info.inputEl.selectionStart === 'number' ? info.inputEl.selectionStart : val.length;
        const beforeCaret = val.slice(0, caret).trimEnd();
        if (!beforeCaret) return false;
        const lastChar = beforeCaret[beforeCaret.length - 1];
        // Expecting a cell reference right after =, (, ,, ;, +, -, *, /, ^, &, <, >, :
        if (['=', '(', ',', ';', '+', '-', '*', '/', '^', '&', '<', '>', ':'].includes(lastChar)) {
            return true;
        }
        // Also allow if the cursor is currently inside or at the end of a cell reference token
        const refAtCaret = /\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?$/.exec(beforeCaret);
        if (refAtCaret) {
            return true;
        }
        return false;
    };

    function ssSyncFormulaEditorValue(info, newValue, newCaretStart, newCaretEnd) {
        if (!info || !info.inputEl) return;
        const sheet = ssGetActiveSheet();
        const targetCoord = info.cellCoord || activeCellCoord || 'A1';

        info.inputEl.value = newValue;
        sheet.cells[targetCoord] = newValue;

        const fBar = document.getElementById('ss-formula-bar-input');
        const cellInput = document.getElementById(`ss-cell-${targetCoord}`);
        if (fBar && fBar !== info.inputEl) {
            fBar.value = newValue;
        }
        if (cellInput && cellInput !== info.inputEl) {
            if (typeof ssEditingCellCoord !== 'undefined' && ssEditingCellCoord === targetCoord) {
                cellInput.value = newValue;
            } else if (typeof ssEvaluateCellDisplay === 'function') {
                cellInput.value = ssEvaluateCellDisplay(newValue, sheet.cells);
            }
            if (typeof ssSyncWrapMirror === 'function') ssSyncWrapMirror(cellInput);
        }

        setTimeout(() => {
            try {
                info.inputEl.focus({ preventScroll: true });
                if (typeof newCaretStart === 'number') {
                    info.inputEl.setSelectionRange(newCaretStart, typeof newCaretEnd === 'number' ? newCaretEnd : newCaretStart);
                }
            } catch (_) {}
        }, 0);

        ssHighlightFormulaReferencedCells(newValue);
        if (typeof scheduleSpreadsheetAutoSyncToGoogleDrive === 'function') {
            scheduleSpreadsheetAutoSyncToGoogleDrive();
        }
    }

    // Highlight any cells/ranges referenced in the currently edited formula
    window.ssHighlightFormulaReferencedCells = function (formulaStr) {
        document.querySelectorAll('#ss-grid-table td.ss-formula-ref-highlight').forEach(td => {
            td.classList.remove('ss-formula-ref-highlight');
        });
        const s = String(formulaStr || '').trim();
        if (!s.startsWith('=')) return;
        const refRegex = /(\$?[A-Za-z]{1,3}\$?\d+)(?::(\$?[A-Za-z]{1,3}\$?\d+))?/g;
        let m;
        while ((m = refRegex.exec(s)) !== null) {
            // Ignore if followed by '(' (which is a function name like LOG10 or ATAN2)
            const afterIdx = m.index + m[0].length;
            if (s[afterIdx] === '(') continue;
            const c1 = m[1].replace(/\$/g, '').toUpperCase();
            const c2 = m[2] ? m[2].replace(/\$/g, '').toUpperCase() : c1;
            const p1 = ssParseCoord(c1);
            const p2 = ssParseCoord(c2);
            if (!p1 || !p2) continue;
            const cMin = Math.min(p1.colIndex, p2.colIndex);
            const cMax = Math.max(p1.colIndex, p2.colIndex);
            const rMin = Math.min(p1.rowNum, p2.rowNum);
            const rMax = Math.max(p1.rowNum, p2.rowNum);
            for (let r = rMin; r <= rMax; r++) {
                for (let c = cMin; c <= cMax; c++) {
                    const td = document.getElementById(`ss-td-${ssColIdxToLetter(c)}${r}`);
                    if (td) td.classList.add('ss-formula-ref-highlight');
                }
            }
        }
    };

    // Handle clicking a cell while in Formula Point Mode (Single Click, Shift+Click, or Ctrl+Click)
    window.ssHandleFormulaPointCellMouseDown = function (event, coord, optionalEndCoord = null) {
        const info = window.ssGetActiveFormulaEditorInfo();
        if (!info || !info.inputEl || !coord) return false;
        if (!optionalEndCoord && coord === info.cellCoord) return false; // Do not self-reference the cell being edited on click

        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }

        const val = String(info.inputEl.value || '');
        const isCtrl = Boolean(event && (event.ctrlKey || event.metaKey));
        const isShift = Boolean(event && event.shiftKey);
        const state = window.ssFormulaPointState;
        const tokenToInsert = (optionalEndCoord && optionalEndCoord !== coord) ? `${coord}:${optionalEndCoord}` : coord;

        let caret = typeof info.inputEl.selectionStart === 'number' ? info.inputEl.selectionStart : val.length;

        if (isShift && state.anchorCoord && state.tokenStart !== null && state.tokenEnd !== null) {
            // Expand current reference token into a range anchor:coord
            const targetEnd = optionalEndCoord || coord;
            const pA = ssParseCoord(state.anchorCoord);
            const pB = ssParseCoord(targetEnd);
            let rangeRef = `${state.anchorCoord}:${targetEnd}`;
            if (pA && pB) {
                const tl = `${ssColIdxToLetter(Math.min(pA.colIndex, pB.colIndex))}${Math.min(pA.rowNum, pB.rowNum)}`;
                const br = `${ssColIdxToLetter(Math.max(pA.colIndex, pB.colIndex))}${Math.max(pA.rowNum, pB.rowNum)}`;
                rangeRef = tl === br ? tl : `${tl}:${br}`;
            }
            const updated = val.slice(0, state.tokenStart) + rangeRef + val.slice(state.tokenEnd);
            state.tokenEnd = state.tokenStart + rangeRef.length;
            state.isDraggingRef = !optionalEndCoord;
            ssSyncFormulaEditorValue(info, updated, state.tokenEnd, state.tokenEnd);
            return true;
        }

        if (isCtrl) {
            // Ctrl+Click: append a new comma-separated cell/range reference (or insert directly if right after '(' or ',')
            const insertPos = state.tokenEnd !== null ? state.tokenEnd : caret;
            const before = val.slice(0, insertPos).trimEnd();
            const lastCh = before[before.length - 1] || '';
            const needsComma = !['=', '(', ',', ';', '+', '-', '*', '/', '^', '&', ':'].includes(lastCh);
            const prefix = needsComma ? ',' : '';
            const inserted = prefix + tokenToInsert;
            const updated = val.slice(0, insertPos) + inserted + val.slice(insertPos);
            state.tokenStart = insertPos + prefix.length;
            state.tokenEnd = state.tokenStart + tokenToInsert.length;
            state.anchorCoord = coord;
            state.isDraggingRef = !optionalEndCoord;
            ssSyncFormulaEditorValue(info, updated, state.tokenEnd, state.tokenEnd);
            return true;
        }

        // Standard Click: if we already have an active pointed token, replace it; or if cursor is on an existing reference token, replace it; otherwise insert at caret
        if (state.tokenStart !== null && state.tokenEnd !== null && state.tokenEnd <= val.length) {
            const updated = val.slice(0, state.tokenStart) + tokenToInsert + val.slice(state.tokenEnd);
            state.tokenEnd = state.tokenStart + tokenToInsert.length;
            state.anchorCoord = coord;
            state.isDraggingRef = !optionalEndCoord;
            ssSyncFormulaEditorValue(info, updated, state.tokenEnd, state.tokenEnd);
            return true;
        }

        // Check if caret is right at the end of an existing reference token (and not a function name)
        const beforeStr = val.slice(0, caret);
        const existingRefMatch = /(?:^|[=(,;+\-*/^&<>:\s])(\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?)$/.exec(beforeStr);
        if (existingRefMatch) {
            const refToken = existingRefMatch[1];
            const tStart = caret - refToken.length;
            const updated = val.slice(0, tStart) + tokenToInsert + val.slice(caret);
            state.tokenStart = tStart;
            state.tokenEnd = tStart + tokenToInsert.length;
            state.anchorCoord = coord;
            state.isDraggingRef = !optionalEndCoord;
            ssSyncFormulaEditorValue(info, updated, state.tokenEnd, state.tokenEnd);
            return true;
        }

        // Insert fresh reference at caret
        const updated = val.slice(0, caret) + tokenToInsert + val.slice(caret);
        state.tokenStart = caret;
        state.tokenEnd = caret + tokenToInsert.length;
        state.anchorCoord = coord;
        state.isDraggingRef = !optionalEndCoord;
        ssSyncFormulaEditorValue(info, updated, state.tokenEnd, state.tokenEnd);
        return true;
    };

    // Handle dragging across cells while in Formula Point Mode
    window.ssHandleFormulaPointCellMouseEnter = function (event, coord) {
        const state = window.ssFormulaPointState;
        if (!state.isDraggingRef || !state.anchorCoord || state.tokenStart === null || state.tokenEnd === null || !coord) {
            return false;
        }
        if (event && event.buttons !== undefined && (event.buttons & 1) === 0) {
            state.isDraggingRef = false;
            return false;
        }
        const info = window.ssGetActiveFormulaEditorInfo();
        if (!info || !info.inputEl) return false;

        const val = String(info.inputEl.value || '');
        const pA = ssParseCoord(state.anchorCoord);
        const pB = ssParseCoord(coord);
        if (!pA || !pB) return false;

        const topLeft = `${ssColIdxToLetter(Math.min(pA.colIndex, pB.colIndex))}${Math.min(pA.rowNum, pB.rowNum)}`;
        const bottomRight = `${ssColIdxToLetter(Math.max(pA.colIndex, pB.colIndex))}${Math.max(pA.rowNum, pB.rowNum)}`;
        const rangeRef = topLeft === bottomRight ? topLeft : `${topLeft}:${bottomRight}`;

        const updated = val.slice(0, state.tokenStart) + rangeRef + val.slice(state.tokenEnd);
        state.tokenEnd = state.tokenStart + rangeRef.length;
        ssSyncFormulaEditorValue(info, updated, state.tokenEnd, state.tokenEnd);
        return true;
    };

    window.addEventListener('mouseup', () => {
        if (window.ssFormulaPointState.isDraggingRef) {
            window.ssFormulaPointState.isDraggingRef = false;
        }
    });

    // --- F4 Shortcut Key: Cycle Relative/Absolute ($) on Cell or Range Reference ---
    function ssCycleSingleCoordDollarState(coordToken, targetStateIdx) {
        const m = /^(\$?)([A-Za-z]{1,3})(\$?)(\d+)$/.exec(String(coordToken || '').trim());
        if (!m) return coordToken;
        const hasColDollar = m[1] === '$';
        const col = m[2].toUpperCase();
        const hasRowDollar = m[3] === '$';
        const row = m[4];

        let stateIdx = targetStateIdx;
        if (typeof stateIdx !== 'number') {
            if (!hasColDollar && !hasRowDollar) stateIdx = 1;      // A1 -> $A$1
            else if (hasColDollar && hasRowDollar) stateIdx = 2;   // $A$1 -> A$1
            else if (!hasColDollar && hasRowDollar) stateIdx = 3;  // A$1 -> $A1
            else stateIdx = 0;                                     // $A1 -> A1
        }
        if (stateIdx === 1) return `$${col}$${row}`;
        if (stateIdx === 2) return `${col}$${row}`;
        if (stateIdx === 3) return `$${col}${row}`;
        return `${col}${row}`;
    }

    function ssCycleRangeOrCellDollarToken(tokenStr) {
        const parts = String(tokenStr || '').split(':');
        const firstPart = parts[0] || '';
        const m = /^(\$?)([A-Za-z]{1,3})(\$?)(\d+)$/.exec(firstPart.trim());
        if (!m) return tokenStr;
        const hasColDollar = m[1] === '$';
        const hasRowDollar = m[3] === '$';
        let nextState = 1;
        if (!hasColDollar && !hasRowDollar) nextState = 1;      // -> $A$1
        else if (hasColDollar && hasRowDollar) nextState = 2;   // -> A$1
        else if (!hasColDollar && hasRowDollar) nextState = 3;  // -> $A1
        else nextState = 0;                                     // -> A1
        return parts.map(p => ssCycleSingleCoordDollarState(p, nextState)).join(':');
    }

    window.ssToggleDollarSignOnActiveFormula = function (explicitInputEl = null) {
        const info = explicitInputEl
            ? { inputEl: explicitInputEl, cellCoord: ssEditingCellCoord || activeCellCoord || 'A1' }
            : window.ssGetActiveFormulaEditorInfo();
        const targetInput = info?.inputEl || document.getElementById('ss-formula-bar-input');
        if (!targetInput) return false;

        const val = String(targetInput.value || '');
        if (!val.trimStart().startsWith('=')) {
            if (typeof showToast === 'function') {
                showToast('💡 Type a formula starting with "=" (e.g. =SUM(A1:A10)) then press F4 to toggle $A$1 absolute references.');
            }
            return false;
        }

        const state = window.ssFormulaPointState;
        const caret = typeof targetInput.selectionStart === 'number' ? targetInput.selectionStart : val.length;

        // Find all cell/range reference tokens in the formula
        const refRegex = /\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?/g;
        const matches = [];
        let m;
        while ((m = refRegex.exec(val)) !== null) {
            const endIdx = m.index + m[0].length;
            if (val[endIdx] === '(') continue; // Skip function names like LOG10( or ATAN2(
            matches.push({ start: m.index, end: endIdx, text: m[0] });
        }
        if (matches.length === 0) return false;

        // Pick the token that contains the caret, or matches state.tokenStart, or fallback to the last reference token
        let chosen = matches.find(tok => caret >= tok.start && caret <= tok.end);
        if (!chosen && state.tokenStart !== null) {
            chosen = matches.find(tok => tok.start === state.tokenStart);
        }
        if (!chosen) {
            chosen = matches[matches.length - 1];
        }

        const cycled = ssCycleRangeOrCellDollarToken(chosen.text);
        const updated = val.slice(0, chosen.start) + cycled + val.slice(chosen.end);
        const newEnd = chosen.start + cycled.length;
        state.tokenStart = chosen.start;
        state.tokenEnd = newEnd;

        ssSyncFormulaEditorValue(
            { inputEl: targetInput, cellCoord: info?.cellCoord || ssEditingCellCoord || activeCellCoord || 'A1' },
            updated,
            newEnd,
            newEnd
        );
        if (typeof scheduleSpreadsheetAutoSyncToGoogleDrive === 'function') {
            scheduleSpreadsheetAutoSyncToGoogleDrive();
        }
        return true;
    };

    // =========================================================================
    // --- MATHEMATICAL & STATISTICAL HELPER UTILITIES ---
    // =========================================================================
    function factorial(n) {
        const k = Math.trunc(n);
        if (k < 0 || k > 170) return NaN;
        let r = 1;
        for (let i = 2; i <= k; i++) r *= i;
        return r;
    }

    function factDouble(n) {
        const k = Math.trunc(n);
        if (k < -1 || k > 300) return NaN;
        let r = 1;
        for (let i = k; i > 1; i -= 2) r *= i;
        return r;
    }

    function gcdTwo(a, b) {
        a = Math.abs(Math.trunc(a));
        b = Math.abs(Math.trunc(b));
        while (b !== 0) {
            const t = b;
            b = a % b;
            a = t;
        }
        return a;
    }

    function lcmTwo(a, b) {
        a = Math.abs(Math.trunc(a));
        b = Math.abs(Math.trunc(b));
        if (a === 0 || b === 0) return 0;
        return (a / gcdTwo(a, b)) * b;
    }

    function erfApprox(x) {
        const sign = x >= 0 ? 1 : -1;
        const ax = Math.abs(x);
        const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741, a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911;
        const t = 1.0 / (1.0 + p * ax);
        const y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-ax * ax);
        return sign * y;
    }

    function gammaLn(z) {
        if (z <= 0) return NaN;
        const c = [
            76.18009172947146, -86.50532032941677, 24.01409824083091,
            -1.231739572450155, 0.001208650973866179, -0.000005395239384953
        ];
        let x = z;
        let y = z;
        let tmp = x + 5.5;
        tmp -= (x + 0.5) * Math.log(tmp);
        let ser = 1.000000000190015;
        for (let j = 0; j < 6; j++) ser += c[j] / ++y;
        return -tmp + Math.log(2.5066282746310005 * ser / x);
    }

    function gammaFn(z) {
        if (z <= 0) return NaN;
        const g = gammaLn(z);
        return Number.isNaN(g) ? NaN : Math.exp(g);
    }

    function normSankPdf(z) {
        return Math.exp(-0.5 * z * z) / Math.sqrt(2 * Math.PI);
    }

    function normSankCdf(z) {
        return 0.5 * (1 + erfApprox(z / Math.SQRT2));
    }

    function normSankInv(p) {
        if (p <= 0 || p >= 1) return NaN;
        // Acklam's rational approximation for standard normal inverse
        const a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00];
        const b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01];
        const c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00];
        const d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00];
        const pLow = 0.02425, pHigh = 1 - pLow;
        let q, r;
        if (p < pLow) {
            q = Math.sqrt(-2 * Math.log(p));
            return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
        } else if (p <= pHigh) {
            q = p - 0.5;
            r = q * q;
            return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
                (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
        } else {
            q = Math.sqrt(-2 * Math.log(1 - p));
            return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
        }
    }

    function toRoman(num) {
        let n = Math.trunc(num);
        if (n <= 0 || n >= 4000) return '#VALUE!';
        const map = [
            [1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'],
            [100, 'C'], [90, 'XC'], [50, 'L'], [40, 'XL'],
            [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I']
        ];
        let out = '';
        for (const [v, sym] of map) {
            while (n >= v) { out += sym; n -= v; }
        }
        return out;
    }

    function fromRoman(str) {
        const s = String(str || '').trim().toUpperCase();
        if (!s) return 0;
        const vals = { I: 1, V: 5, X: 10, L: 50, C: 100, D: 500, M: 1000 };
        let total = 0;
        for (let i = 0; i < s.length; i++) {
            const cur = vals[s[i]];
            const nxt = vals[s[i + 1]] || 0;
            if (!cur) return NaN;
            if (cur < nxt) total -= cur;
            else total += cur;
        }
        return total;
    }

    function parseComplex(str) {
        const s = String(str ?? '').trim().replace(/\s+/g, '');
        if (!s) return { re: 0, im: 0, suffix: 'i' };
        const n = Number(s);
        if (Number.isFinite(n)) return { re: n, im: 0, suffix: 'i' };
        const suffix = s.endsWith('j') ? 'j' : 'i';
        if (s === 'i' || s === '+i' || s === 'j' || s === '+j') return { re: 0, im: 1, suffix };
        if (s === '-i' || s === '-j') return { re: 0, im: -1, suffix };
        const mPureIm = /^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)[ij]$/.exec(s);
        if (mPureIm) return { re: 0, im: Number(mPureIm[1]), suffix };
        const mFull = /^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)([+-]\d*(?:\.\d+)?(?:[eE][+-]?\d+)?)[ij]$/.exec(s);
        if (mFull) {
            const re = Number(mFull[1]);
            const imRaw = mFull[2];
            const im = (imRaw === '+' || imRaw === '') ? 1 : (imRaw === '-' ? -1 : Number(imRaw));
            return { re, im, suffix };
        }
        return null;
    }

    function formatComplex(re, im, suffix = 'i') {
        const r = Math.abs(re) < 1e-12 ? 0 : Number(re.toFixed(6));
        const i = Math.abs(im) < 1e-12 ? 0 : Number(im.toFixed(6));
        if (i === 0) return String(r);
        const imPart = Math.abs(i) === 1 ? (i > 0 ? suffix : `-${suffix}`) : `${i}${suffix}`;
        if (r === 0) return imPart;
        return i > 0 ? `${r}+${Math.abs(i) === 1 ? suffix : `${i}${suffix}`}` : `${r}${imPart}`;
    }

    function parseExcelDate(val) {
        if (val instanceof Date && !Number.isNaN(val.getTime())) return val;
        const s = String(val ?? '').trim();
        if (!s) return null;
        if (/^\d{4,6}(\.\d+)?$/.test(s)) {
            // Excel serial date (days since 1899-12-30)
            const serial = Number(s);
            if (serial > 1 && serial < 2958465) {
                return new Date(Math.round((serial - 25569) * 86400000));
            }
        }
        const dt = new Date(s);
        if (!Number.isNaN(dt.getTime())) return dt;
        return null;
    }

    function dateToExcelSerial(dt) {
        return Math.floor(dt.getTime() / 86400000) + 25569;
    }

    function formatIsoDate(dt) {
        const y = dt.getUTCFullYear();
        const m = String(dt.getUTCMonth() + 1).padStart(2, '0');
        const d = String(dt.getUTCDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
    }

    function percentileInc(sortedNums, k) {
        if (!sortedNums.length || k < 0 || k > 1) return NaN;
        const pos = k * (sortedNums.length - 1);
        const base = Math.floor(pos);
        const rest = pos - base;
        if (base + 1 < sortedNums.length) {
            return sortedNums[base] + rest * (sortedNums[base + 1] - sortedNums[base]);
        }
        return sortedNums[base];
    }

    function percentileExc(sortedNums, k) {
        const n = sortedNums.length;
        if (!n || k <= 1 / (n + 1) || k >= n / (n + 1)) return NaN;
        const pos = k * (n + 1) - 1;
        const base = Math.floor(pos);
        const rest = pos - base;
        return sortedNums[base] + rest * (sortedNums[base + 1] - sortedNums[base]);
    }

    // =========================================================================
    // --- COMPREHENSIVE 10-CATEGORY FORMULA EVALUATOR ---
    // =========================================================================
    window.ssEvaluateExtendedFormula = function (fnName, rawArgs, helpers) {
        const {
            cellsMap,
            getCellEval,
            toFloat,
            toBool,
            expandRangeCoords,
            expandArgValues,
            expandArgNumbers,
            evalExpr,
            formatNum,
            matchesCriteria,
            splitArgs
        } = helpers;

        const fn = String(fnName || '').toUpperCase().replace(/^_XLFN\./, '').replace(/^_XLFN\.XWS\./, '');
        if (BLOCKED_IMAGE_FORMULAS.has(fn) || fn.includes('IMAGE')) {
            return '#IMAGE_FORMULA_NOT_ALLOWED!';
        }

        // Helper: resolve a range argument into a 2D matrix of evaluated strings
        const getRangeMatrixValues = (argStr) => {
            const clean = String(argStr || '').trim();
            if (/^\$?[A-Za-z]+\$?\d+:\$?[A-Za-z]+\$?\d+$/.test(clean)) {
                const coordsMat = expandRangeCoords(clean);
                return coordsMat.map(row => row.map(c => getCellEval(c)));
            }
            const single = String(evalExpr(clean));
            if (single.includes(' | ')) {
                return single.split(' ; ').map(r => r.split(' | '));
            }
            return [[single]];
        };

        const formatMatrixOutput = (mat) => {
            if (!Array.isArray(mat) || !mat.length) return '';
            if (mat.length === 1 && mat[0].length === 1) return String(mat[0][0] ?? '');
            if (mat.length === 1) return mat[0].join(', ');
            if (mat.every(r => r.length === 1)) return mat.map(r => r[0]).join(', ');
            return mat.map(r => r.join(', ')).join(' | ');
        };

        // =====================================================================
        // 1. LOOKUP, REFERENCE & DYNAMIC ARRAY FORMULAS
        // =====================================================================
        if (fn === 'ADDRESS') {
            if (rawArgs.length < 2) return '#VALUE!';
            const r = Math.max(1, Math.trunc(toFloat(evalExpr(rawArgs[0]), 1)));
            const c = Math.max(1, Math.trunc(toFloat(evalExpr(rawArgs[1]), 1)));
            const absNum = rawArgs.length > 2 ? Math.trunc(toFloat(evalExpr(rawArgs[2]), 1)) : 1;
            const a1Style = rawArgs.length > 3 ? toBool(evalExpr(rawArgs[3])) : true;
            const sheetText = rawArgs.length > 4 ? String(evalExpr(rawArgs[4])).trim() : '';
            const prefix = sheetText ? (/\s/.test(sheetText) ? `'${sheetText}'!` : `${sheetText}!`) : '';
            if (!a1Style) {
                return `${prefix}R${r}C${c}`;
            }
            const colL = ssColIdxToLetter(c - 1);
            if (absNum === 2) return `${prefix}${colL}$${r}`;
            if (absNum === 3) return `${prefix}$${colL}${r}`;
            if (absNum === 4) return `${prefix}${colL}${r}`;
            return `${prefix}$${colL}$${r}`;
        }
        if (fn === 'AREAS') {
            return String(Math.max(1, rawArgs.length));
        }
        if (fn === 'FORMULATEXT') {
            if (!rawArgs.length) return '#N/A';
            const ref = String(rawArgs[0]).replace(/\$/g, '').trim().toUpperCase();
            const rawCell = String(cellsMap[ref] ?? '');
            return rawCell.startsWith('=') ? rawCell : '#N/A';
        }
        if (fn === 'INDIRECT') {
            if (!rawArgs.length) return '#REF!';
            const refStr = String(evalExpr(rawArgs[0])).replace(/\$/g, '').trim().toUpperCase();
            if (/^[A-Z]+\d+$/.test(refStr)) return getCellEval(refStr);
            if (/^[A-Z]+\d+:[A-Z]+\d+$/.test(refStr)) {
                return formatMatrixOutput(getRangeMatrixValues(refStr));
            }
            return '#REF!';
        }
        if (fn === 'OFFSET') {
            if (rawArgs.length < 3) return '#VALUE!';
            const baseRef = String(rawArgs[0]).replace(/\$/g, '').split(':')[0].trim();
            const p = ssParseCoord(baseRef);
            if (!p) return '#REF!';
            const dRow = Math.trunc(toFloat(evalExpr(rawArgs[1]), 0));
            const dCol = Math.trunc(toFloat(evalExpr(rawArgs[2]), 0));
            const height = rawArgs.length > 3 ? Math.max(1, Math.trunc(toFloat(evalExpr(rawArgs[3]), 1))) : 1;
            const width = rawArgs.length > 4 ? Math.max(1, Math.trunc(toFloat(evalExpr(rawArgs[4]), 1))) : 1;
            const startCol = p.colIndex + dCol;
            const startRow = p.rowNum + dRow;
            if (startCol < 0 || startRow < 1) return '#REF!';
            if (height === 1 && width === 1) {
                return getCellEval(`${ssColIdxToLetter(startCol)}${startRow}`);
            }
            const endCoord = `${ssColIdxToLetter(startCol + width - 1)}${startRow + height - 1}`;
            return formatMatrixOutput(getRangeMatrixValues(`${ssColIdxToLetter(startCol)}${startRow}:${endCoord}`));
        }
        if (fn === 'LOOKUP') {
            if (rawArgs.length < 2) return '#VALUE!';
            const lookupVal = String(evalExpr(rawArgs[0])).trim();
            const searchVals = expandArgValues(rawArgs[1]);
            const resultVals = rawArgs.length > 2 ? expandArgValues(rawArgs[2]) : searchVals;
            let matchedIdx = -1;
            for (let i = 0; i < searchVals.length; i++) {
                if (matchesCriteria(searchVals[i], lookupVal) || String(searchVals[i]).toLowerCase() <= lookupVal.toLowerCase()) {
                    matchedIdx = i;
                }
            }
            return matchedIdx >= 0 && matchedIdx < resultVals.length ? resultVals[matchedIdx] : '#N/A';
        }
        if (fn === 'XMATCH') {
            if (rawArgs.length < 2) return '#VALUE!';
            const lookupVal = String(evalExpr(rawArgs[0])).trim();
            const lVals = expandArgValues(rawArgs[1]);
            const searchMode = rawArgs.length > 3 ? Math.trunc(toFloat(evalExpr(rawArgs[3]), 1)) : 1;
            if (searchMode === -1) {
                for (let i = lVals.length - 1; i >= 0; i--) {
                    if (matchesCriteria(lVals[i], lookupVal)) return String(i + 1);
                }
            } else {
                for (let i = 0; i < lVals.length; i++) {
                    if (matchesCriteria(lVals[i], lookupVal)) return String(i + 1);
                }
            }
            return '#N/A';
        }
        if (fn === 'HYPERLINK') {
            if (!rawArgs.length) return '';
            const url = String(evalExpr(rawArgs[0]));
            const friendly = rawArgs.length > 1 ? String(evalExpr(rawArgs[1])) : url;
            return friendly || url;
        }
        if (fn === 'UNIQUE') {
            if (!rawArgs.length) return '';
            const byCol = rawArgs.length > 1 ? toBool(evalExpr(rawArgs[1])) : false;
            const exactlyOnce = rawArgs.length > 2 ? toBool(evalExpr(rawArgs[2])) : false;
            const vals = expandArgValues(rawArgs[0]).filter(v => String(v).trim() !== '');
            const counts = new Map();
            vals.forEach(v => counts.set(v, (counts.get(v) || 0) + 1));
            const out = [];
            const seen = new Set();
            vals.forEach(v => {
                if (exactlyOnce) {
                    if (counts.get(v) === 1) out.push(v);
                } else if (!seen.has(v)) {
                    seen.add(v);
                    out.push(v);
                }
            });
            return byCol ? out.join(', ') : out.join(', ');
        }
        if (fn === 'SORT') {
            if (!rawArgs.length) return '';
            const mat = getRangeMatrixValues(rawArgs[0]);
            const sortIdx = rawArgs.length > 1 ? Math.max(1, Math.trunc(toFloat(evalExpr(rawArgs[1]), 1))) - 1 : 0;
            const sortOrder = rawArgs.length > 2 ? Math.trunc(toFloat(evalExpr(rawArgs[2]), 1)) : 1;
            const sorted = [...mat].sort((a, b) => {
                const va = a[sortIdx] ?? '';
                const vb = b[sortIdx] ?? '';
                const na = toFloat(va, null);
                const nb = toFloat(vb, null);
                if (na !== null && nb !== null) return (na - nb) * sortOrder;
                return String(va).localeCompare(String(vb)) * sortOrder;
            });
            return formatMatrixOutput(sorted);
        }
        if (fn === 'SORTBY') {
            if (rawArgs.length < 2) return '#VALUE!';
            const arr = expandArgValues(rawArgs[0]);
            const byArr = expandArgValues(rawArgs[1]);
            const order = rawArgs.length > 2 ? Math.trunc(toFloat(evalExpr(rawArgs[2]), 1)) : 1;
            const zipped = arr.map((v, i) => ({ v, k: byArr[i] ?? '' }));
            zipped.sort((a, b) => {
                const na = toFloat(a.k, null);
                const nb = toFloat(b.k, null);
                if (na !== null && nb !== null) return (na - nb) * order;
                return String(a.k).localeCompare(String(b.k)) * order;
            });
            return zipped.map(z => z.v).join(', ');
        }
        if (fn === 'FILTER') {
            if (rawArgs.length < 2) return '#VALUE!';
            const mat = getRangeMatrixValues(rawArgs[0]);
            const condRange = rawArgs[1].trim();
            const ifEmpty = rawArgs.length > 2 ? String(evalExpr(rawArgs[2])) : '#CALC!';
            // Support expressions like B2:B6>10 or B2:B6="Tech"
            const cmpMatch = /^(\$?[A-Za-z]+\$?\d+:\$?[A-Za-z]+\$?\d+)\s*(<>|>=|<=|=|>|<)\s*([\s\S]+)$/.exec(condRange);
            let mask = [];
            if (cmpMatch) {
                const rVals = expandArgValues(cmpMatch[1]);
                const op = cmpMatch[2];
                const rhs = evalExpr(cmpMatch[3]);
                mask = rVals.map(v => matchesCriteria(v, `${op}${rhs}`));
            } else {
                mask = expandArgValues(condRange).map(v => toBool(v));
            }
            const filtered = mat.filter((_, idx) => Boolean(mask[idx]));
            return filtered.length ? formatMatrixOutput(filtered) : ifEmpty;
        }
        if (fn === 'TRANSPOSE') {
            if (!rawArgs.length) return '';
            const mat = getRangeMatrixValues(rawArgs[0]);
            if (!mat.length || !mat[0].length) return '';
            const transposed = mat[0].map((_, cIdx) => mat.map(row => row[cIdx] ?? ''));
            return formatMatrixOutput(transposed);
        }
        if (fn === 'TOCOL' || fn === 'TOROW') {
            const vals = rawArgs.length ? expandArgValues(rawArgs[0]).filter(v => v !== '') : [];
            return vals.join(', ');
        }
        if (fn === 'VSTACK' || fn === 'HSTACK') {
            const all = rawArgs.flatMap(a => expandArgValues(a)).filter(v => v !== '');
            return all.join(', ');
        }
        if (fn === 'TAKE') {
            if (rawArgs.length < 2) return '#VALUE!';
            const mat = getRangeMatrixValues(rawArgs[0]);
            const rows = Math.trunc(toFloat(evalExpr(rawArgs[1]), mat.length));
            const cols = rawArgs.length > 2 ? Math.trunc(toFloat(evalExpr(rawArgs[2]), mat[0]?.length || 1)) : (mat[0]?.length || 1);
            const rSlice = rows >= 0 ? mat.slice(0, rows) : mat.slice(rows);
            const cSlice = rSlice.map(r => (cols >= 0 ? r.slice(0, cols) : r.slice(cols)));
            return formatMatrixOutput(cSlice);
        }
        if (fn === 'DROP') {
            if (rawArgs.length < 2) return '#VALUE!';
            const mat = getRangeMatrixValues(rawArgs[0]);
            const rows = Math.trunc(toFloat(evalExpr(rawArgs[1]), 0));
            const cols = rawArgs.length > 2 ? Math.trunc(toFloat(evalExpr(rawArgs[2]), 0)) : 0;
            const rSlice = rows >= 0 ? mat.slice(rows) : mat.slice(0, mat.length + rows);
            const cSlice = rSlice.map(r => (cols >= 0 ? r.slice(cols) : r.slice(0, r.length + cols)));
            return formatMatrixOutput(cSlice);
        }
        if (fn === 'CHOOSEROWS') {
            if (rawArgs.length < 2) return '#VALUE!';
            const mat = getRangeMatrixValues(rawArgs[0]);
            const indices = rawArgs.slice(1).map(a => Math.trunc(toFloat(evalExpr(a), 1)));
            const out = indices.map(idx => {
                const rIdx = idx > 0 ? idx - 1 : mat.length + idx;
                return mat[rIdx] || [];
            });
            return formatMatrixOutput(out);
        }
        if (fn === 'CHOOSECOLS') {
            if (rawArgs.length < 2) return '#VALUE!';
            const mat = getRangeMatrixValues(rawArgs[0]);
            const indices = rawArgs.slice(1).map(a => Math.trunc(toFloat(evalExpr(a), 1)));
            const out = mat.map(row => indices.map(idx => {
                const cIdx = idx > 0 ? idx - 1 : row.length + idx;
                return row[cIdx] ?? '';
            }));
            return formatMatrixOutput(out);
        }
        if (fn === 'WRAPROWS' || fn === 'WRAPCOLS') {
            if (rawArgs.length < 2) return '#VALUE!';
            const vals = expandArgValues(rawArgs[0]);
            const wrapCount = Math.max(1, Math.trunc(toFloat(evalExpr(rawArgs[1]), 1)));
            const padWith = rawArgs.length > 2 ? String(evalExpr(rawArgs[2])) : '#N/A';
            const chunks = [];
            for (let i = 0; i < vals.length; i += wrapCount) {
                const chunk = vals.slice(i, i + wrapCount);
                while (chunk.length < wrapCount) chunk.push(padWith);
                chunks.push(chunk);
            }
            return formatMatrixOutput(chunks);
        }
        if (fn === 'EXPAND') {
            if (rawArgs.length < 2) return '#VALUE!';
            const mat = getRangeMatrixValues(rawArgs[0]);
            const rows = Math.max(mat.length, Math.trunc(toFloat(evalExpr(rawArgs[1]), mat.length)));
            const cols = rawArgs.length > 2 ? Math.max(mat[0]?.length || 1, Math.trunc(toFloat(evalExpr(rawArgs[2]), mat[0]?.length || 1))) : (mat[0]?.length || 1);
            const pad = rawArgs.length > 3 ? String(evalExpr(rawArgs[3])) : '#N/A';
            const out = [];
            for (let r = 0; r < rows; r++) {
                const row = [];
                for (let c = 0; c < cols; c++) {
                    row.push((mat[r] && mat[r][c] !== undefined) ? mat[r][c] : pad);
                }
                out.push(row);
            }
            return formatMatrixOutput(out);
        }
        if (fn === 'PERCENTOF') {
            if (rawArgs.length < 2) return '#VALUE!';
            const sub = expandArgNumbers(rawArgs[0]).reduce((a, b) => a + b, 0);
            const tot = expandArgNumbers(rawArgs[1]).reduce((a, b) => a + b, 0);
            return tot === 0 ? '#DIV/0!' : formatNum(sub / tot);
        }
        if (fn === 'GROUPBY' || fn === 'PIVOTBY') {
            if (rawArgs.length < 3) return '#VALUE!';
            const keys = expandArgValues(rawArgs[0]);
            const vals = expandArgValues(rawArgs[1]).map(v => toFloat(v, 0));
            const aggMap = new Map();
            keys.forEach((k, idx) => {
                if (!k) return;
                aggMap.set(k, (aggMap.get(k) || 0) + (vals[idx] || 0));
            });
            return Array.from(aggMap.entries()).map(([k, v]) => `${k}: ${formatNum(v)}`).join(' | ');
        }
        if (fn === 'GETPIVOTDATA' || fn === 'RTD') {
            return rawArgs.length ? String(evalExpr(rawArgs[0])) : '0';
        }

        // =====================================================================
        // 2. TEXT FORMULAS
        // =====================================================================
        if (fn === 'ARRAYTOTEXT') {
            return rawArgs.flatMap(a => expandArgValues(a)).filter(v => v !== '').join(', ');
        }
        if (fn === 'VALUETOTEXT') {
            if (!rawArgs.length) return '';
            const v = String(evalExpr(rawArgs[0]));
            const fmt = rawArgs.length > 1 ? Math.trunc(toFloat(evalExpr(rawArgs[1]), 0)) : 0;
            return (fmt === 1 && toFloat(v, null) === null) ? `"${v}"` : v;
        }
        if (fn === 'CHAR' || fn === 'UNICHAR') {
            if (!rawArgs.length) return '#VALUE!';
            const code = Math.trunc(toFloat(evalExpr(rawArgs[0]), 0));
            return code > 0 ? String.fromCodePoint(code) : '#VALUE!';
        }
        if (fn === 'CODE' || fn === 'UNICODE') {
            if (!rawArgs.length) return '#VALUE!';
            const s = String(evalExpr(rawArgs[0]));
            return s.length ? String(s.codePointAt(0)) : '#VALUE!';
        }
        if (fn === 'CLEAN') {
            return rawArgs.length ? String(evalExpr(rawArgs[0])).replace(/[\x00-\x1F\x7F]/g, '') : '';
        }
        if (fn === 'ASC') {
            if (!rawArgs.length) return '';
            return String(evalExpr(rawArgs[0])).replace(/[\uFF01-\uFF5E]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0xFEE0)).replace(/\u3000/g, ' ');
        }
        if (fn === 'DBCS' || fn === 'JIS') {
            if (!rawArgs.length) return '';
            return String(evalExpr(rawArgs[0])).replace(/[\x21-\x7E]/g, ch => String.fromCharCode(ch.charCodeAt(0) + 0xFEE0));
        }
        if (fn === 'DOLLAR') {
            if (!rawArgs.length) return '$0.00';
            const n = toFloat(evalExpr(rawArgs[0]), 0);
            const dec = rawArgs.length > 1 ? Math.max(0, Math.trunc(toFloat(evalExpr(rawArgs[1]), 2))) : 2;
            const sign = n < 0 ? '-' : '';
            return `${sign}$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec })}`;
        }
        if (fn === 'FIXED') {
            if (!rawArgs.length) return '0.00';
            const n = toFloat(evalExpr(rawArgs[0]), 0);
            const dec = rawArgs.length > 1 ? Math.max(0, Math.trunc(toFloat(evalExpr(rawArgs[1]), 2))) : 2;
            const noCommas = rawArgs.length > 2 ? toBool(evalExpr(rawArgs[2])) : false;
            return noCommas
                ? n.toFixed(dec)
                : n.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
        }
        if (fn === 'BAHTTEXT') {
            if (!rawArgs.length) return '0 Baht';
            const n = toFloat(evalExpr(rawArgs[0]), 0);
            return `฿${n.toFixed(2)}`;
        }
        if (fn === 'FINDB' || fn === 'SEARCHB') {
            if (rawArgs.length < 2) return '#VALUE!';
            const needle = String(evalExpr(rawArgs[0]));
            const hay = String(evalExpr(rawArgs[1]));
            const start = rawArgs.length > 2 ? Math.max(1, Math.trunc(toFloat(evalExpr(rawArgs[2]), 1))) : 1;
            const idx = fn === 'SEARCHB'
                ? hay.toLowerCase().indexOf(needle.toLowerCase(), start - 1)
                : hay.indexOf(needle, start - 1);
            return idx >= 0 ? String(idx + 1) : '#VALUE!';
        }
        if (fn === 'LEFTB') {
            const s = rawArgs.length ? String(evalExpr(rawArgs[0])) : '';
            const n = rawArgs.length > 1 ? Math.max(0, Math.trunc(toFloat(evalExpr(rawArgs[1]), 1))) : 1;
            return s.slice(0, n);
        }
        if (fn === 'RIGHTB') {
            const s = rawArgs.length ? String(evalExpr(rawArgs[0])) : '';
            const n = rawArgs.length > 1 ? Math.max(0, Math.trunc(toFloat(evalExpr(rawArgs[1]), 1))) : 1;
            return n > 0 ? s.slice(-n) : '';
        }
        if (fn === 'MIDB') {
            if (rawArgs.length < 3) return '#VALUE!';
            const s = String(evalExpr(rawArgs[0]));
            const st = Math.max(1, Math.trunc(toFloat(evalExpr(rawArgs[1]), 1)));
            const ln = Math.max(0, Math.trunc(toFloat(evalExpr(rawArgs[2]), 0)));
            return s.slice(st - 1, st - 1 + ln);
        }
        if (fn === 'LENB') {
            return rawArgs.length ? String(new TextEncoder().encode(String(evalExpr(rawArgs[0]))).length) : '0';
        }
        if (fn === 'REPLACEB') {
            if (rawArgs.length < 4) return '#VALUE!';
            const s = String(evalExpr(rawArgs[0]));
            const st = Math.max(1, Math.trunc(toFloat(evalExpr(rawArgs[1]), 1)));
            const ln = Math.max(0, Math.trunc(toFloat(evalExpr(rawArgs[2]), 0)));
            const nw = String(evalExpr(rawArgs[3]));
            return s.slice(0, st - 1) + nw + s.slice(st - 1 + ln);
        }
        if (fn === 'NUMBERVALUE') {
            if (!rawArgs.length) return '0';
            let txt = String(evalExpr(rawArgs[0])).trim();
            const decSep = rawArgs.length > 1 ? String(evalExpr(rawArgs[1]))[0] || '.' : '.';
            const grpSep = rawArgs.length > 2 ? String(evalExpr(rawArgs[2]))[0] || ',' : ',';
            if (grpSep) txt = txt.split(grpSep).join('');
            if (decSep && decSep !== '.') txt = txt.replace(decSep, '.');
            const fv = toFloat(txt, null);
            return fv !== null ? formatNum(fv) : '#VALUE!';
        }
        if (fn === 'T' || fn === 'PHONETIC') {
            if (!rawArgs.length) return '';
            const v = String(evalExpr(rawArgs[0]));
            return toFloat(v, null) !== null ? '' : v;
        }
        if (fn === 'TEXT') {
            if (!rawArgs.length) return '';
            const rawVal = evalExpr(rawArgs[0]);
            if (rawArgs.length < 2) return String(rawVal);
            const fmt = String(evalExpr(rawArgs[1])).trim();
            const num = toFloat(rawVal, null);
            if (num !== null) {
                if (fmt.includes('%')) {
                    const decMatch = /\.([0#]+)/.exec(fmt);
                    const dec = decMatch ? decMatch[1].length : 0;
                    return `${(num * 100).toFixed(dec)}%`;
                }
                const currencyMatch = /^([$₱€£¥])/.exec(fmt);
                const curr = currencyMatch ? currencyMatch[1] : '';
                const useComma = fmt.includes(',');
                const decMatch = /\.([0#]+)/.exec(fmt);
                const dec = decMatch ? decMatch[1].length : 0;
                const sign = num < 0 ? '-' : '';
                const absN = Math.abs(num);
                const formatted = useComma
                    ? absN.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec })
                    : absN.toFixed(dec);
                return `${sign}${curr}${formatted}`;
            }
            return String(rawVal);
        }
        if (fn === 'TEXTBEFORE') {
            if (rawArgs.length < 2) return '#VALUE!';
            const txt = String(evalExpr(rawArgs[0]));
            const delim = String(evalExpr(rawArgs[1]));
            const inst = rawArgs.length > 2 ? Math.trunc(toFloat(evalExpr(rawArgs[2]), 1)) : 1;
            if (!delim) return '';
            const parts = txt.split(delim);
            if (parts.length <= 1) return rawArgs.length > 5 ? String(evalExpr(rawArgs[5])) : '#N/A';
            const idx = inst > 0 ? inst : parts.length + inst;
            if (idx < 1 || idx >= parts.length) return '#N/A';
            return parts.slice(0, idx).join(delim);
        }
        if (fn === 'TEXTAFTER') {
            if (rawArgs.length < 2) return '#VALUE!';
            const txt = String(evalExpr(rawArgs[0]));
            const delim = String(evalExpr(rawArgs[1]));
            const inst = rawArgs.length > 2 ? Math.trunc(toFloat(evalExpr(rawArgs[2]), 1)) : 1;
            if (!delim) return txt;
            const parts = txt.split(delim);
            if (parts.length <= 1) return rawArgs.length > 5 ? String(evalExpr(rawArgs[5])) : '#N/A';
            const idx = inst > 0 ? inst : parts.length + inst;
            if (idx < 1 || idx >= parts.length) return '#N/A';
            return parts.slice(idx).join(delim);
        }
        if (fn === 'TEXTSPLIT') {
            if (rawArgs.length < 2) return '#VALUE!';
            const txt = String(evalExpr(rawArgs[0]));
            const colDelim = String(evalExpr(rawArgs[1]));
            return colDelim ? txt.split(colDelim).map(s => s.trim()).join(', ') : txt;
        }
        if (fn === 'REGEXTEST') {
            if (rawArgs.length < 2) return 'FALSE';
            try {
                const txt = String(evalExpr(rawArgs[0]));
                const pat = String(evalExpr(rawArgs[1]));
                const flags = (rawArgs.length > 2 && toFloat(evalExpr(rawArgs[2]), 0) === 1) ? 'i' : '';
                return new RegExp(pat, flags).test(txt) ? 'TRUE' : 'FALSE';
            } catch (_) {
                return '#VALUE!';
            }
        }
        if (fn === 'REGEXEXTRACT') {
            if (rawArgs.length < 2) return '#VALUE!';
            try {
                const txt = String(evalExpr(rawArgs[0]));
                const pat = String(evalExpr(rawArgs[1]));
                const mode = rawArgs.length > 2 ? Math.trunc(toFloat(evalExpr(rawArgs[2]), 0)) : 0;
                const re = new RegExp(pat, mode === 1 ? 'g' : '');
                if (mode === 1) {
                    const m = txt.match(re);
                    return m ? m.join(', ') : '#N/A';
                }
                const m = re.exec(txt);
                return m ? (m[1] !== undefined ? m[1] : m[0]) : '#N/A';
            } catch (_) {
                return '#VALUE!';
            }
        }
        if (fn === 'REGEXREPLACE') {
            if (rawArgs.length < 3) return '#VALUE!';
            try {
                const txt = String(evalExpr(rawArgs[0]));
                const pat = String(evalExpr(rawArgs[1]));
                const rep = String(evalExpr(rawArgs[2]));
                return txt.replace(new RegExp(pat, 'g'), rep);
            } catch (_) {
                return '#VALUE!';
            }
        }
        if (fn === 'DETECTLANGUAGE') {
            if (!rawArgs.length) return 'en';
            const s = String(evalExpr(rawArgs[0])).toLowerCase();
            if (/\b(ang|mga|sa|ng|ito|para|hindi|oo|po)\b/.test(s)) return 'tl';
            if (/[\u3040-\u30FF]/.test(s)) return 'ja';
            if (/[\u4E00-\u9FFF]/.test(s)) return 'zh';
            if (/[\uAC00-\uD7AF]/.test(s)) return 'ko';
            return 'en';
        }
        if (fn === 'TRANSLATE') {
            return rawArgs.length ? String(evalExpr(rawArgs[0])) : '';
        }

        // =====================================================================
        // 3. LOGICAL & LAMBDA HELPER FORMULAS
        // =====================================================================
        if (fn === 'LET') {
            if (rawArgs.length < 3 || rawArgs.length % 2 === 0) return '#VALUE!';
            let bodyExpr = rawArgs[rawArgs.length - 1];
            for (let i = 0; i + 1 < rawArgs.length - 1; i += 2) {
                const varName = rawArgs[i].trim();
                const varVal = String(evalExpr(rawArgs[i + 1]));
                const replacement = toFloat(varVal, null) !== null ? varVal : `"${varVal.replace(/"/g, '""')}"`;
                bodyExpr = bodyExpr.replace(new RegExp(`\\b${varName}\\b`, 'g'), replacement);
            }
            return evalExpr(bodyExpr);
        }
        if (fn === 'ISOMITTED') {
            return (!rawArgs.length || String(rawArgs[0]).trim() === '') ? 'TRUE' : 'FALSE';
        }
        if (fn === 'LAMBDA') {
            if (!rawArgs.length) return '#VALUE!';
            return evalExpr(rawArgs[rawArgs.length - 1]);
        }
        const evalLambdaOnValue = (lambdaStr, val1, val2 = null) => {
            const lm = /^LAMBDA\s*\(([\s\S]*)\)$/i.exec(String(lambdaStr || '').trim());
            if (!lm) {
                // Support shorthand function names like SUM, AVERAGE, MAX
                return window.ssEvaluateExtendedFormula(lambdaStr, [String(val1)], helpers);
            }
            const lArgs = splitArgs(lm[1]);
            if (lArgs.length < 2) return val1;
            let body = lArgs[lArgs.length - 1];
            const p1 = lArgs[0].trim();
            const rep1 = toFloat(val1, null) !== null ? String(val1) : `"${String(val1).replace(/"/g, '""')}"`;
            body = body.replace(new RegExp(`\\b${p1}\\b`, 'g'), rep1);
            if (val2 !== null && lArgs.length >= 3) {
                const p2 = lArgs[1].trim();
                const rep2 = toFloat(val2, null) !== null ? String(val2) : `"${String(val2).replace(/"/g, '""')}"`;
                body = body.replace(new RegExp(`\\b${p2}\\b`, 'g'), rep2);
            }
            return evalExpr(body);
        };
        if (fn === 'MAP') {
            if (rawArgs.length < 2) return '#VALUE!';
            const vals = expandArgValues(rawArgs[0]);
            const lambdaStr = rawArgs[rawArgs.length - 1];
            return vals.map(v => evalLambdaOnValue(lambdaStr, v)).join(', ');
        }
        if (fn === 'REDUCE') {
            if (rawArgs.length < 3) return '#VALUE!';
            let acc = evalExpr(rawArgs[0]);
            const vals = expandArgValues(rawArgs[1]);
            const lambdaStr = rawArgs[2];
            vals.forEach(v => { acc = evalLambdaOnValue(lambdaStr, acc, v); });
            return String(acc);
        }
        if (fn === 'SCAN') {
            if (rawArgs.length < 3) return '#VALUE!';
            let acc = evalExpr(rawArgs[0]);
            const vals = expandArgValues(rawArgs[1]);
            const lambdaStr = rawArgs[2];
            const out = [];
            vals.forEach(v => {
                acc = evalLambdaOnValue(lambdaStr, acc, v);
                out.push(acc);
            });
            return out.join(', ');
        }
        if (fn === 'BYROW') {
            if (rawArgs.length < 2) return '#VALUE!';
            const mat = getRangeMatrixValues(rawArgs[0]);
            const lambdaStr = rawArgs[1];
            return mat.map(row => {
                const nums = row.map(v => toFloat(v, null)).filter(n => n !== null);
                if (/SUM/i.test(lambdaStr)) return formatNum(nums.reduce((a, b) => a + b, 0));
                if (/AVERAGE|AVG/i.test(lambdaStr)) return nums.length ? formatNum(nums.reduce((a, b) => a + b, 0) / nums.length) : '0';
                if (/MAX/i.test(lambdaStr)) return nums.length ? formatNum(Math.max(...nums)) : '0';
                if (/MIN/i.test(lambdaStr)) return nums.length ? formatNum(Math.min(...nums)) : '0';
                return evalLambdaOnValue(lambdaStr, row[0] ?? '');
            }).join(', ');
        }
        if (fn === 'BYCOL') {
            if (rawArgs.length < 2) return '#VALUE!';
            const mat = getRangeMatrixValues(rawArgs[0]);
            const lambdaStr = rawArgs[1];
            if (!mat.length || !mat[0].length) return '';
            const cols = mat[0].map((_, cIdx) => mat.map(r => r[cIdx] ?? ''));
            return cols.map(col => {
                const nums = col.map(v => toFloat(v, null)).filter(n => n !== null);
                if (/SUM/i.test(lambdaStr)) return formatNum(nums.reduce((a, b) => a + b, 0));
                if (/AVERAGE|AVG/i.test(lambdaStr)) return nums.length ? formatNum(nums.reduce((a, b) => a + b, 0) / nums.length) : '0';
                return evalLambdaOnValue(lambdaStr, col[0] ?? '');
            }).join(', ');
        }
        if (fn === 'MAKEARRAY') {
            if (rawArgs.length < 3) return '#VALUE!';
            const rCnt = Math.max(1, Math.min(50, Math.trunc(toFloat(evalExpr(rawArgs[0]), 1))));
            const cCnt = Math.max(1, Math.min(50, Math.trunc(toFloat(evalExpr(rawArgs[1]), 1))));
            const lambdaStr = rawArgs[2];
            const mat = [];
            for (let r = 1; r <= rCnt; r++) {
                const row = [];
                for (let c = 1; c <= cCnt; c++) {
                    row.push(evalLambdaOnValue(lambdaStr, r, c));
                }
                mat.push(row);
            }
            return formatMatrixOutput(mat);
        }

        // =====================================================================
        // 4. MATH & TRIGONOMETRY FORMULAS
        // =====================================================================
        if (fn === 'FACT') {
            if (!rawArgs.length) return '#VALUE!';
            return formatNum(factorial(toFloat(evalExpr(rawArgs[0]), 0)));
        }
        if (fn === 'ACOS') return formatNum(Math.acos(toFloat(evalExpr(rawArgs[0]), 0)));
        if (fn === 'ACOSH') return formatNum(Math.acosh(toFloat(evalExpr(rawArgs[0]), 1)));
        if (fn === 'ASIN') return formatNum(Math.asin(toFloat(evalExpr(rawArgs[0]), 0)));
        if (fn === 'ASINH') return formatNum(Math.asinh(toFloat(evalExpr(rawArgs[0]), 0)));
        if (fn === 'ATAN') return formatNum(Math.atan(toFloat(evalExpr(rawArgs[0]), 0)));
        if (fn === 'ATANH') return formatNum(Math.atanh(toFloat(evalExpr(rawArgs[0]), 0)));
        if (fn === 'ATAN2') {
            if (rawArgs.length < 2) return '#VALUE!';
            const x = toFloat(evalExpr(rawArgs[0]), 0);
            const y = toFloat(evalExpr(rawArgs[1]), 0);
            return (x === 0 && y === 0) ? '#DIV/0!' : formatNum(Math.atan2(y, x));
        }
        if (fn === 'COSH') return formatNum(Math.cosh(toFloat(evalExpr(rawArgs[0]), 0)));
        if (fn === 'SINH') return formatNum(Math.sinh(toFloat(evalExpr(rawArgs[0]), 0)));
        if (fn === 'TANH') return formatNum(Math.tanh(toFloat(evalExpr(rawArgs[0]), 0)));
        if (fn === 'COT') {
            const t = Math.tan(toFloat(evalExpr(rawArgs[0]), 0));
            return t === 0 ? '#DIV/0!' : formatNum(1 / t);
        }
        if (fn === 'COTH') {
            const t = Math.tanh(toFloat(evalExpr(rawArgs[0]), 0));
            return t === 0 ? '#DIV/0!' : formatNum(1 / t);
        }
        if (fn === 'ACOT') return formatNum(Math.PI / 2 - Math.atan(toFloat(evalExpr(rawArgs[0]), 0)));
        if (fn === 'ACOTH') {
            const x = toFloat(evalExpr(rawArgs[0]), 0);
            return Math.abs(x) <= 1 ? '#NUM!' : formatNum(0.5 * Math.log((x + 1) / (x - 1)));
        }
        if (fn === 'CSC') {
            const s = Math.sin(toFloat(evalExpr(rawArgs[0]), 0));
            return s === 0 ? '#DIV/0!' : formatNum(1 / s);
        }
        if (fn === 'CSCH') {
            const s = Math.sinh(toFloat(evalExpr(rawArgs[0]), 0));
            return s === 0 ? '#DIV/0!' : formatNum(1 / s);
        }
        if (fn === 'SEC') {
            const c = Math.cos(toFloat(evalExpr(rawArgs[0]), 0));
            return c === 0 ? '#DIV/0!' : formatNum(1 / c);
        }
        if (fn === 'SECH') return formatNum(1 / Math.cosh(toFloat(evalExpr(rawArgs[0]), 0)));
        if (fn === 'SQRTPI') {
            const n = toFloat(evalExpr(rawArgs[0]), 0);
            return n < 0 ? '#NUM!' : formatNum(Math.sqrt(n * Math.PI));
        }
        if (fn === 'CEILING.MATH' || fn === 'CEILING.PRECISE' || fn === 'ISO.CEILING') {
            const n = toFloat(evalExpr(rawArgs[0]), 0);
            const sig = rawArgs.length > 1 ? Math.abs(toFloat(evalExpr(rawArgs[1]), 1)) : 1;
            return sig === 0 ? '0' : formatNum(Math.ceil(n / sig) * sig);
        }
        if (fn === 'FLOOR.MATH' || fn === 'FLOOR.PRECISE') {
            const n = toFloat(evalExpr(rawArgs[0]), 0);
            const sig = rawArgs.length > 1 ? Math.abs(toFloat(evalExpr(rawArgs[1]), 1)) : 1;
            return sig === 0 ? '0' : formatNum(Math.floor(n / sig) * sig);
        }
        if (fn === 'MROUND') {
            if (rawArgs.length < 2) return '#VALUE!';
            const n = toFloat(evalExpr(rawArgs[0]), 0);
            const mult = toFloat(evalExpr(rawArgs[1]), 1);
            if (mult === 0) return '0';
            if ((n > 0 && mult < 0) || (n < 0 && mult > 0)) return '#NUM!';
            return formatNum(Math.round(n / mult) * mult);
        }
        if (fn === 'EVEN') {
            const n = toFloat(evalExpr(rawArgs[0]), 0);
            const sign = n < 0 ? -1 : 1;
            const c = Math.ceil(Math.abs(n));
            return formatNum(sign * (c % 2 === 0 ? c : c + 1));
        }
        if (fn === 'ODD') {
            const n = toFloat(evalExpr(rawArgs[0]), 0);
            if (n === 0) return '1';
            const sign = n < 0 ? -1 : 1;
            const c = Math.ceil(Math.abs(n));
            return formatNum(sign * (c % 2 === 1 ? c : c + 1));
        }
        if (fn === 'QUOTIENT') {
            if (rawArgs.length < 2) return '#VALUE!';
            const num = toFloat(evalExpr(rawArgs[0]), 0);
            const den = toFloat(evalExpr(rawArgs[1]), 0);
            return den === 0 ? '#DIV/0!' : String(Math.trunc(num / den));
        }
        if (fn === 'FACTDOUBLE') return formatNum(factDouble(toFloat(evalExpr(rawArgs[0]), 0)));
        if (fn === 'COMBIN') {
            if (rawArgs.length < 2) return '#VALUE!';
            const n = Math.trunc(toFloat(evalExpr(rawArgs[0]), 0));
            const k = Math.trunc(toFloat(evalExpr(rawArgs[1]), 0));
            if (n < 0 || k < 0 || k > n) return '#NUM!';
            return formatNum(factorial(n) / (factorial(k) * factorial(n - k)));
        }
        if (fn === 'COMBINA') {
            if (rawArgs.length < 2) return '#VALUE!';
            const n = Math.trunc(toFloat(evalExpr(rawArgs[0]), 0));
            const k = Math.trunc(toFloat(evalExpr(rawArgs[1]), 0));
            if (n < 0 || k < 0) return '#NUM!';
            if (n === 0 && k === 0) return '1';
            const tot = n + k - 1;
            return formatNum(factorial(tot) / (factorial(k) * factorial(tot - k)));
        }
        if (fn === 'GCD') {
            const nums = rawArgs.flatMap(a => expandArgNumbers(a));
            return nums.length ? String(nums.reduce((a, b) => gcdTwo(a, b))) : '0';
        }
        if (fn === 'LCM') {
            const nums = rawArgs.flatMap(a => expandArgNumbers(a));
            return nums.length ? String(nums.reduce((a, b) => lcmTwo(a, b))) : '0';
        }
        if (fn === 'MULTINOMIAL') {
            const nums = rawArgs.flatMap(a => expandArgNumbers(a)).map(n => Math.trunc(n));
            if (nums.some(n => n < 0)) return '#NUM!';
            const sumN = nums.reduce((a, b) => a + b, 0);
            const denom = nums.reduce((acc, n) => acc * factorial(n), 1);
            return formatNum(factorial(sumN) / denom);
        }
        if (fn === 'BASE') {
            if (rawArgs.length < 2) return '#VALUE!';
            const n = Math.trunc(toFloat(evalExpr(rawArgs[0]), 0));
            const radix = Math.trunc(toFloat(evalExpr(rawArgs[1]), 10));
            const minLen = rawArgs.length > 2 ? Math.max(0, Math.trunc(toFloat(evalExpr(rawArgs[2]), 0))) : 0;
            if (n < 0 || radix < 2 || radix > 36) return '#NUM!';
            return n.toString(radix).toUpperCase().padStart(minLen, '0');
        }
        if (fn === 'DECIMAL') {
            if (rawArgs.length < 2) return '#VALUE!';
            const s = String(evalExpr(rawArgs[0])).trim();
            const radix = Math.trunc(toFloat(evalExpr(rawArgs[1]), 10));
            if (radix < 2 || radix > 36) return '#NUM!';
            const parsed = parseInt(s, radix);
            return Number.isNaN(parsed) ? '#NUM!' : String(parsed);
        }
        if (fn === 'ROMAN') return rawArgs.length ? toRoman(toFloat(evalExpr(rawArgs[0]), 0)) : '';
        if (fn === 'ARABIC') {
            const r = rawArgs.length ? fromRoman(evalExpr(rawArgs[0])) : 0;
            return Number.isNaN(r) ? '#VALUE!' : String(r);
        }
        if (fn === 'RAND') return formatNum(Math.random());
        if (fn === 'RANDBETWEEN') {
            if (rawArgs.length < 2) return '#VALUE!';
            const low = Math.ceil(toFloat(evalExpr(rawArgs[0]), 0));
            const high = Math.floor(toFloat(evalExpr(rawArgs[1]), 1));
            if (low > high) return '#NUM!';
            return String(Math.floor(low + Math.random() * (high - low + 1)));
        }
        if (fn === 'RANDARRAY') {
            const rCnt = rawArgs.length > 0 ? Math.max(1, Math.min(20, Math.trunc(toFloat(evalExpr(rawArgs[0]), 1)))) : 1;
            const cCnt = rawArgs.length > 1 ? Math.max(1, Math.min(20, Math.trunc(toFloat(evalExpr(rawArgs[1]), 1)))) : 1;
            const mn = rawArgs.length > 2 ? toFloat(evalExpr(rawArgs[2]), 0) : 0;
            const mx = rawArgs.length > 3 ? toFloat(evalExpr(rawArgs[3]), 1) : 1;
            const whole = rawArgs.length > 4 ? toBool(evalExpr(rawArgs[4])) : false;
            const out = [];
            for (let i = 0; i < rCnt * cCnt; i++) {
                const v = mn + Math.random() * (mx - mn);
                out.push(whole ? String(Math.round(v)) : formatNum(v));
            }
            return out.join(', ');
        }
        if (fn === 'SEQUENCE') {
            const rows = rawArgs.length > 0 ? Math.max(1, Math.min(200, Math.trunc(toFloat(evalExpr(rawArgs[0]), 1)))) : 1;
            const cols = rawArgs.length > 1 ? Math.max(1, Math.min(50, Math.trunc(toFloat(evalExpr(rawArgs[1]), 1)))) : 1;
            const start = rawArgs.length > 2 ? toFloat(evalExpr(rawArgs[2]), 1) : 1;
            const step = rawArgs.length > 3 ? toFloat(evalExpr(rawArgs[3]), 1) : 1;
            const out = [];
            let cur = start;
            for (let i = 0; i < rows * cols; i++) {
                out.push(formatNum(cur));
                cur += step;
            }
            return out.join(', ');
        }
        if (fn === 'SERIESSUM') {
            if (rawArgs.length < 4) return '#VALUE!';
            const x = toFloat(evalExpr(rawArgs[0]), 0);
            const n = toFloat(evalExpr(rawArgs[1]), 0);
            const m = toFloat(evalExpr(rawArgs[2]), 1);
            const coeffs = expandArgNumbers(rawArgs[3]);
            const res = coeffs.reduce((acc, a, i) => acc + a * Math.pow(x, n + i * m), 0);
            return formatNum(res);
        }
        if (fn === 'SUMSQ') {
            const nums = rawArgs.flatMap(a => expandArgNumbers(a));
            return formatNum(nums.reduce((a, b) => a + b * b, 0));
        }
        if (fn === 'SUMX2MY2' || fn === 'SUMX2PY2' || fn === 'SUMXMY2') {
            if (rawArgs.length < 2) return '#VALUE!';
            const x = expandArgNumbers(rawArgs[0]);
            const y = expandArgNumbers(rawArgs[1]);
            const len = Math.min(x.length, y.length);
            let sum = 0;
            for (let i = 0; i < len; i++) {
                if (fn === 'SUMX2MY2') sum += (x[i] * x[i] - y[i] * y[i]);
                else if (fn === 'SUMX2PY2') sum += (x[i] * x[i] + y[i] * y[i]);
                else sum += Math.pow(x[i] - y[i], 2);
            }
            return formatNum(sum);
        }
        if (fn === 'SUBTOTAL' || fn === 'AGGREGATE') {
            if (rawArgs.length < 2) return '#VALUE!';
            const code = Math.trunc(toFloat(evalExpr(rawArgs[0]), 9)) % 100;
            const rangeArgs = fn === 'AGGREGATE' && rawArgs.length > 2 ? rawArgs.slice(2) : rawArgs.slice(1);
            const mapFn = {
                1: 'AVERAGE', 2: 'COUNT', 3: 'COUNTA', 4: 'MAX', 5: 'MIN',
                6: 'PRODUCT', 7: 'STDEV.S', 8: 'STDEV.P', 9: 'SUM', 10: 'VAR.S',
                11: 'VAR.P', 12: 'MEDIAN', 13: 'MODE.SNGL', 14: 'LARGE', 15: 'SMALL'
            }[code] || 'SUM';
            return evalExpr(`${mapFn}(${rangeArgs.join(',')})`);
        }
        if (fn === 'MUNIT') {
            const n = rawArgs.length ? Math.max(1, Math.min(10, Math.trunc(toFloat(evalExpr(rawArgs[0]), 1)))) : 1;
            const mat = [];
            for (let r = 0; r < n; r++) {
                const row = [];
                for (let c = 0; c < n; c++) row.push(r === c ? '1' : '0');
                mat.push(row);
            }
            return formatMatrixOutput(mat);
        }
        if (fn === 'MDETERM') {
            const mat = rawArgs.length ? getRangeMatrixValues(rawArgs[0]).map(r => r.map(v => toFloat(v, 0))) : [];
            const n = mat.length;
            if (!n || mat[0].length !== n) return '#VALUE!';
            if (n === 1) return formatNum(mat[0][0]);
            if (n === 2) return formatNum(mat[0][0] * mat[1][1] - mat[0][1] * mat[1][0]);
            if (n === 3) {
                const d = mat[0][0] * (mat[1][1] * mat[2][2] - mat[1][2] * mat[2][1])
                    - mat[0][1] * (mat[1][0] * mat[2][2] - mat[1][2] * mat[2][0])
                    + mat[0][2] * (mat[1][0] * mat[2][1] - mat[1][1] * mat[2][0]);
                return formatNum(d);
            }
            return '0';
        }
        if (fn === 'MMULT') {
            if (rawArgs.length < 2) return '#VALUE!';
            const A = getRangeMatrixValues(rawArgs[0]).map(r => r.map(v => toFloat(v, 0)));
            const B = getRangeMatrixValues(rawArgs[1]).map(r => r.map(v => toFloat(v, 0)));
            if (!A.length || !B.length || A[0].length !== B.length) return '#VALUE!';
            const out = A.map(rowA => B[0].map((_, cIdx) => {
                const s = rowA.reduce((acc, val, k) => acc + val * (B[k][cIdx] || 0), 0);
                return formatNum(s);
            }));
            return formatMatrixOutput(out);
        }
        if (fn === 'MINVERSE') {
            const A = rawArgs.length ? getRangeMatrixValues(rawArgs[0]).map(r => r.map(v => toFloat(v, 0))) : [];
            if (A.length === 1 && A[0].length === 1) {
                return A[0][0] === 0 ? '#NUM!' : formatNum(1 / A[0][0]);
            }
            if (A.length === 2 && A[0].length === 2) {
                const det = A[0][0] * A[1][1] - A[0][1] * A[1][0];
                if (det === 0) return '#NUM!';
                return formatMatrixOutput([
                    [formatNum(A[1][1] / det), formatNum(-A[0][1] / det)],
                    [formatNum(-A[1][0] / det), formatNum(A[0][0] / det)]
                ]);
            }
            return '#VALUE!';
        }

        // =====================================================================
        // 5. STATISTICAL FORMULAS
        // =====================================================================
        const expandArgNumbersWithTextLogical = (argExpr) => {
            const vals = expandArgValues(argExpr);
            return vals.filter(v => String(v).trim() !== '').map(v => {
                const sv = String(v).trim().toUpperCase();
                if (sv === 'TRUE') return 1;
                if (sv === 'FALSE') return 0;
                const n = toFloat(v, null);
                return n !== null ? n : 0;
            });
        };
        if (fn === 'AVERAGEA') {
            const nums = rawArgs.flatMap(a => expandArgNumbersWithTextLogical(a));
            return nums.length ? formatNum(nums.reduce((a, b) => a + b, 0) / nums.length) : '#DIV/0!';
        }
        if (fn === 'MAXA') {
            const nums = rawArgs.flatMap(a => expandArgNumbersWithTextLogical(a));
            return nums.length ? formatNum(Math.max(...nums)) : '0';
        }
        if (fn === 'MINA') {
            const nums = rawArgs.flatMap(a => expandArgNumbersWithTextLogical(a));
            return nums.length ? formatNum(Math.min(...nums)) : '0';
        }
        if (fn === 'VARA' || fn === 'VARPA' || fn === 'STDEVA' || fn === 'STDEVPA') {
            const nums = rawArgs.flatMap(a => expandArgNumbersWithTextLogical(a));
            const isPop = fn.endsWith('PA');
            if (nums.length < (isPop ? 1 : 2)) return '#DIV/0!';
            const mean = nums.reduce((a, b) => a + b, 0) / nums.length;
            const v = nums.reduce((a, x) => a + Math.pow(x - mean, 2), 0) / (isPop ? nums.length : nums.length - 1);
            return formatNum(fn.startsWith('STDEV') ? Math.sqrt(v) : v);
        }
        if (fn === 'AVEDEV') {
            const nums = rawArgs.flatMap(a => expandArgNumbers(a));
            if (!nums.length) return '#NUM!';
            const mean = nums.reduce((a, b) => a + b, 0) / nums.length;
            return formatNum(nums.reduce((a, x) => a + Math.abs(x - mean), 0) / nums.length);
        }
        if (fn === 'DEVSQ') {
            const nums = rawArgs.flatMap(a => expandArgNumbers(a));
            if (!nums.length) return '0';
            const mean = nums.reduce((a, b) => a + b, 0) / nums.length;
            return formatNum(nums.reduce((a, x) => a + Math.pow(x - mean, 2), 0));
        }
        if (fn === 'GEOMEAN') {
            const nums = rawArgs.flatMap(a => expandArgNumbers(a));
            if (!nums.length || nums.some(n => n <= 0)) return '#NUM!';
            const logSum = nums.reduce((a, n) => a + Math.log(n), 0);
            return formatNum(Math.exp(logSum / nums.length));
        }
        if (fn === 'HARMEAN') {
            const nums = rawArgs.flatMap(a => expandArgNumbers(a));
            if (!nums.length || nums.some(n => n <= 0)) return '#NUM!';
            const invSum = nums.reduce((a, n) => a + 1 / n, 0);
            return formatNum(nums.length / invSum);
        }
        if (fn === 'TRIMMEAN') {
            if (rawArgs.length < 2) return '#VALUE!';
            const nums = expandArgNumbers(rawArgs[0]).sort((a, b) => a - b);
            const pct = toFloat(evalExpr(rawArgs[1]), 0);
            if (!nums.length || pct < 0 || pct >= 1) return '#NUM!';
            const cut = Math.floor((nums.length * pct) / 2);
            const trimmed = nums.slice(cut, nums.length - cut);
            return trimmed.length ? formatNum(trimmed.reduce((a, b) => a + b, 0) / trimmed.length) : '#DIV/0!';
        }
        if (fn === 'MODE.SNGL' || fn === 'MODE.MULT') {
            const nums = rawArgs.flatMap(a => expandArgNumbers(a));
            if (!nums.length) return '#N/A';
            const counts = new Map();
            let maxCnt = 0;
            nums.forEach(n => {
                const c = (counts.get(n) || 0) + 1;
                counts.set(n, c);
                if (c > maxCnt) maxCnt = c;
            });
            const modes = Array.from(counts.entries()).filter(([, c]) => c === maxCnt).map(([n]) => formatNum(n));
            return fn === 'MODE.MULT' ? modes.join(', ') : modes[0];
        }
        if (fn === 'RANK' || fn === 'RANK.EQ' || fn === 'RANK.AVG') {
            if (rawArgs.length < 2) return '#VALUE!';
            const target = toFloat(evalExpr(rawArgs[0]), null);
            const nums = expandArgNumbers(rawArgs[1]);
            const asc = rawArgs.length > 2 ? toFloat(evalExpr(rawArgs[2]), 0) !== 0 : false;
            if (target === null || !nums.length) return '#N/A';
            const sorted = [...nums].sort((a, b) => asc ? a - b : b - a);
            const firstIdx = sorted.findIndex(n => Math.abs(n - target) < 1e-9);
            if (firstIdx < 0) return '#N/A';
            if (fn === 'RANK.AVG') {
                const matches = sorted.map((n, idx) => Math.abs(n - target) < 1e-9 ? idx + 1 : -1).filter(i => i > 0);
                return formatNum(matches.reduce((a, b) => a + b, 0) / matches.length);
            }
            return String(firstIdx + 1);
        }
        if (fn === 'PERCENTILE' || fn === 'PERCENTILE.INC' || fn === 'PERCENTILE.EXC') {
            if (rawArgs.length < 2) return '#VALUE!';
            const nums = expandArgNumbers(rawArgs[0]).sort((a, b) => a - b);
            const k = toFloat(evalExpr(rawArgs[1]), 0);
            const res = fn === 'PERCENTILE.EXC' ? percentileExc(nums, k) : percentileInc(nums, k);
            return Number.isNaN(res) ? '#NUM!' : formatNum(res);
        }
        if (fn === 'QUARTILE' || fn === 'QUARTILE.INC' || fn === 'QUARTILE.EXC') {
            if (rawArgs.length < 2) return '#VALUE!';
            const nums = expandArgNumbers(rawArgs[0]).sort((a, b) => a - b);
            const q = Math.trunc(toFloat(evalExpr(rawArgs[1]), 0));
            const res = fn === 'QUARTILE.EXC' ? percentileExc(nums, q * 0.25) : percentileInc(nums, q * 0.25);
            return Number.isNaN(res) ? '#NUM!' : formatNum(res);
        }
        if (fn === 'PERCENTRANK' || fn === 'PERCENTRANK.INC' || fn === 'PERCENTRANK.EXC') {
            if (rawArgs.length < 2) return '#VALUE!';
            const nums = expandArgNumbers(rawArgs[0]).sort((a, b) => a - b);
            const x = toFloat(evalExpr(rawArgs[1]), 0);
            if (!nums.length || x < nums[0] || x > nums[nums.length - 1]) return '#N/A';
            const lessCount = nums.filter(n => n < x).length;
            const denom = fn === 'PERCENTRANK.EXC' ? (nums.length + 1) : Math.max(1, nums.length - 1);
            return formatNum((fn === 'PERCENTRANK.EXC' ? lessCount + 1 : lessCount) / denom);
        }
        if (fn === 'PERMUT') {
            if (rawArgs.length < 2) return '#VALUE!';
            const n = Math.trunc(toFloat(evalExpr(rawArgs[0]), 0));
            const k = Math.trunc(toFloat(evalExpr(rawArgs[1]), 0));
            if (n < 0 || k < 0 || k > n) return '#NUM!';
            return formatNum(factorial(n) / factorial(n - k));
        }
        if (fn === 'PERMUTATIONA') {
            if (rawArgs.length < 2) return '#VALUE!';
            return formatNum(Math.pow(toFloat(evalExpr(rawArgs[0]), 0), toFloat(evalExpr(rawArgs[1]), 0)));
        }
        if (fn === 'STANDARDIZE') {
            if (rawArgs.length < 3) return '#VALUE!';
            const x = toFloat(evalExpr(rawArgs[0]), 0);
            const mean = toFloat(evalExpr(rawArgs[1]), 0);
            const sd = toFloat(evalExpr(rawArgs[2]), 1);
            return sd <= 0 ? '#NUM!' : formatNum((x - mean) / sd);
        }
        if (fn === 'CORREL' || fn === 'PEARSON' || fn === 'RSQ' || fn === 'COVARIANCE.P' || fn === 'COVARIANCE.S' || fn === 'SLOPE' || fn === 'INTERCEPT' || fn === 'STEYX' || fn === 'FORECAST' || fn === 'FORECAST.LINEAR' || fn === 'FORECAST.ETS' || fn === 'TREND' || fn === 'GROWTH' || fn === 'LINEST' || fn === 'LOGEST') {
            const isForecast = fn.startsWith('FORECAST');
            const xTarget = isForecast ? toFloat(evalExpr(rawArgs[0]), 0) : 0;
            const yArg = isForecast ? rawArgs[1] : rawArgs[0];
            const xArg = isForecast ? rawArgs[2] : rawArgs[1];
            const Y = yArg ? expandArgNumbers(yArg) : [];
            const X = xArg ? expandArgNumbers(xArg) : Y.map((_, i) => i + 1);
            const n = Math.min(X.length, Y.length);
            if (n < 1) return '#N/A';
            const meanX = X.slice(0, n).reduce((a, b) => a + b, 0) / n;
            const meanY = Y.slice(0, n).reduce((a, b) => a + b, 0) / n;
            let cov = 0, varX = 0, varY = 0;
            for (let i = 0; i < n; i++) {
                const dx = X[i] - meanX;
                const dy = Y[i] - meanY;
                cov += dx * dy;
                varX += dx * dx;
                varY += dy * dy;
            }
            if (fn === 'COVARIANCE.P') return formatNum(cov / n);
            if (fn === 'COVARIANCE.S') return n < 2 ? '#DIV/0!' : formatNum(cov / (n - 1));
            if (varX === 0) return '#DIV/0!';
            const slope = cov / varX;
            const intercept = meanY - slope * meanX;
            if (fn === 'SLOPE' || fn === 'LINEST') return formatNum(slope);
            if (fn === 'INTERCEPT') return formatNum(intercept);
            if (fn === 'LOGEST' || fn === 'GROWTH') return formatNum(Math.exp(slope));
            if (isForecast || fn === 'TREND') {
                const targetX = isForecast ? xTarget : (rawArgs.length > 2 ? toFloat(evalExpr(rawArgs[2]), n + 1) : X[0]);
                return formatNum(intercept + slope * targetX);
            }
            if (varY === 0) return '#DIV/0!';
            const r = cov / Math.sqrt(varX * varY);
            if (fn === 'CORREL' || fn === 'PEARSON') return formatNum(r);
            if (fn === 'RSQ') return formatNum(r * r);
            if (fn === 'STEYX') {
                if (n < 3) return '#DIV/0!';
                const sse = Math.max(0, varY - (cov * cov) / varX);
                return formatNum(Math.sqrt(sse / (n - 2)));
            }
        }
        if (fn === 'FORECAST.ETS.CONFINT' || fn === 'FORECAST.ETS.STAT') return '0.05';
        if (fn === 'FORECAST.ETS.SEASONALITY') return '1';
        if (fn === 'SKEW' || fn === 'SKEW.P' || fn === 'KURT') {
            const nums = rawArgs.flatMap(a => expandArgNumbers(a));
            const n = nums.length;
            if (n < 3) return '#DIV/0!';
            const mean = nums.reduce((a, b) => a + b, 0) / n;
            const sd = Math.sqrt(nums.reduce((a, x) => a + Math.pow(x - mean, 2), 0) / (fn === 'SKEW.P' ? n : n - 1));
            if (sd === 0) return '#DIV/0!';
            if (fn === 'SKEW.P') {
                return formatNum(nums.reduce((a, x) => a + Math.pow((x - mean) / sd, 3), 0) / n);
            }
            if (fn === 'SKEW') {
                return formatNum((n / ((n - 1) * (n - 2))) * nums.reduce((a, x) => a + Math.pow((x - mean) / sd, 3), 0));
            }
            if (n < 4) return '#DIV/0!';
            const s4 = nums.reduce((a, x) => a + Math.pow((x - mean) / sd, 4), 0);
            return formatNum(((n * (n + 1)) / ((n - 1) * (n - 2) * (n - 3))) * s4 - (3 * Math.pow(n - 1, 2)) / ((n - 2) * (n - 3)));
        }
        if (fn === 'PHI') return formatNum(normSankPdf(toFloat(evalExpr(rawArgs[0]), 0)));
        if (fn === 'GAUSS') return formatNum(normSankCdf(toFloat(evalExpr(rawArgs[0]), 0)) - 0.5);
        if (fn === 'FISHER') {
            const x = toFloat(evalExpr(rawArgs[0]), 0);
            return Math.abs(x) >= 1 ? '#NUM!' : formatNum(0.5 * Math.log((1 + x) / (1 - x)));
        }
        if (fn === 'FISHERINV') {
            const y = toFloat(evalExpr(rawArgs[0]), 0);
            return formatNum((Math.exp(2 * y) - 1) / (Math.exp(2 * y) + 1));
        }
        if (fn === 'GAMMA') return formatNum(gammaFn(toFloat(evalExpr(rawArgs[0]), 1)));
        if (fn === 'GAMMALN' || fn === 'GAMMALN.PRECISE') return formatNum(gammaLn(toFloat(evalExpr(rawArgs[0]), 1)));
        if (fn === 'NORM.S.DIST') {
            const z = toFloat(evalExpr(rawArgs[0]), 0);
            const cum = rawArgs.length > 1 ? toBool(evalExpr(rawArgs[1])) : true;
            return formatNum(cum ? normSankCdf(z) : normSankPdf(z));
        }
        if (fn === 'NORM.S.INV') return formatNum(normSankInv(toFloat(evalExpr(rawArgs[0]), 0.5)));
        if (fn === 'NORM.DIST') {
            if (rawArgs.length < 4) return '#VALUE!';
            const x = toFloat(evalExpr(rawArgs[0]), 0);
            const mean = toFloat(evalExpr(rawArgs[1]), 0);
            const sd = toFloat(evalExpr(rawArgs[2]), 1);
            const cum = toBool(evalExpr(rawArgs[3]));
            if (sd <= 0) return '#NUM!';
            const z = (x - mean) / sd;
            return formatNum(cum ? normSankCdf(z) : normSankPdf(z) / sd);
        }
        if (fn === 'NORM.INV') {
            if (rawArgs.length < 3) return '#VALUE!';
            const p = toFloat(evalExpr(rawArgs[0]), 0.5);
            const mean = toFloat(evalExpr(rawArgs[1]), 0);
            const sd = toFloat(evalExpr(rawArgs[2]), 1);
            return sd <= 0 ? '#NUM!' : formatNum(mean + sd * normSankInv(p));
        }
        if (fn === 'LOGNORM.DIST') {
            if (rawArgs.length < 4) return '#VALUE!';
            const x = toFloat(evalExpr(rawArgs[0]), 1);
            const mean = toFloat(evalExpr(rawArgs[1]), 0);
            const sd = toFloat(evalExpr(rawArgs[2]), 1);
            const cum = toBool(evalExpr(rawArgs[3]));
            if (x <= 0 || sd <= 0) return '#NUM!';
            const z = (Math.log(x) - mean) / sd;
            return formatNum(cum ? normSankCdf(z) : normSankPdf(z) / (x * sd));
        }
        if (fn === 'LOGNORM.INV') {
            if (rawArgs.length < 3) return '#VALUE!';
            const p = toFloat(evalExpr(rawArgs[0]), 0.5);
            const mean = toFloat(evalExpr(rawArgs[1]), 0);
            const sd = toFloat(evalExpr(rawArgs[2]), 1);
            return formatNum(Math.exp(mean + sd * normSankInv(p)));
        }
        if (fn === 'CONFIDENCE.NORM' || fn === 'CONFIDENCE.T') {
            if (rawArgs.length < 3) return '#VALUE!';
            const alpha = toFloat(evalExpr(rawArgs[0]), 0.05);
            const sd = toFloat(evalExpr(rawArgs[1]), 1);
            const size = toFloat(evalExpr(rawArgs[2]), 1);
            if (alpha <= 0 || alpha >= 1 || sd <= 0 || size < 1) return '#NUM!';
            return formatNum(normSankInv(1 - alpha / 2) * (sd / Math.sqrt(size)));
        }
        if (fn === 'EXPON.DIST') {
            if (rawArgs.length < 3) return '#VALUE!';
            const x = toFloat(evalExpr(rawArgs[0]), 0);
            const lam = toFloat(evalExpr(rawArgs[1]), 1);
            const cum = toBool(evalExpr(rawArgs[2]));
            if (x < 0 || lam <= 0) return '#NUM!';
            return formatNum(cum ? 1 - Math.exp(-lam * x) : lam * Math.exp(-lam * x));
        }
        if (fn === 'WEIBULL.DIST') {
            if (rawArgs.length < 4) return '#VALUE!';
            const x = toFloat(evalExpr(rawArgs[0]), 0);
            const alpha = toFloat(evalExpr(rawArgs[1]), 1);
            const beta = toFloat(evalExpr(rawArgs[2]), 1);
            const cum = toBool(evalExpr(rawArgs[3]));
            if (x < 0 || alpha <= 0 || beta <= 0) return '#NUM!';
            return formatNum(cum
                ? 1 - Math.exp(-Math.pow(x / beta, alpha))
                : (alpha / Math.pow(beta, alpha)) * Math.pow(x, alpha - 1) * Math.exp(-Math.pow(x / beta, alpha)));
        }
        if (fn === 'POISSON.DIST') {
            if (rawArgs.length < 3) return '#VALUE!';
            const x = Math.trunc(toFloat(evalExpr(rawArgs[0]), 0));
            const mean = toFloat(evalExpr(rawArgs[1]), 1);
            const cum = toBool(evalExpr(rawArgs[2]));
            if (x < 0 || mean < 0) return '#NUM!';
            const pmf = (k) => Math.exp(-mean) * Math.pow(mean, k) / factorial(k);
            if (!cum) return formatNum(pmf(x));
            let s = 0;
            for (let k = 0; k <= x; k++) s += pmf(k);
            return formatNum(s);
        }
        if (fn === 'BINOM.DIST' || fn === 'BINOM.DIST.RANGE') {
            if (rawArgs.length < 3) return '#VALUE!';
            const s = Math.trunc(toFloat(evalExpr(rawArgs[0]), 0));
            const n = Math.trunc(toFloat(evalExpr(rawArgs[1]), 1));
            const p = toFloat(evalExpr(rawArgs[2]), 0.5);
            const cum = rawArgs.length > 3 ? toBool(evalExpr(rawArgs[3])) : false;
            const pmf = (k) => (factorial(n) / (factorial(k) * factorial(n - k))) * Math.pow(p, k) * Math.pow(1 - p, n - k);
            if (fn === 'BINOM.DIST.RANGE') {
                const s2 = rawArgs.length > 3 ? Math.trunc(toFloat(evalExpr(rawArgs[3]), p)) : n;
                let sum = 0;
                const kStart = Math.trunc(toFloat(evalExpr(rawArgs[2]), 0));
                const kEnd = rawArgs.length > 3 ? s2 : kStart;
                const prob = toFloat(evalExpr(rawArgs[1]), 0.5);
                const trials = Math.trunc(toFloat(evalExpr(rawArgs[0]), 1));
                for (let k = kStart; k <= kEnd; k++) {
                    sum += (factorial(trials) / (factorial(k) * factorial(trials - k))) * Math.pow(prob, k) * Math.pow(1 - prob, trials - k);
                }
                return formatNum(sum);
            }
            if (!cum) return formatNum(pmf(s));
            let tot = 0;
            for (let k = 0; k <= s; k++) tot += pmf(k);
            return formatNum(tot);
        }
        if (fn === 'BINOM.INV') {
            if (rawArgs.length < 3) return '#VALUE!';
            const trials = Math.trunc(toFloat(evalExpr(rawArgs[0]), 1));
            const p = toFloat(evalExpr(rawArgs[1]), 0.5);
            const alpha = toFloat(evalExpr(rawArgs[2]), 0.5);
            let cdf = 0;
            for (let k = 0; k <= trials; k++) {
                cdf += (factorial(trials) / (factorial(k) * factorial(trials - k))) * Math.pow(p, k) * Math.pow(1 - p, trials - k);
                if (cdf >= alpha) return String(k);
            }
            return String(trials);
        }
        if (fn === 'HYPGEOM.DIST' || fn === 'NEGBINOM.DIST') {
            if (rawArgs.length < 4) return '#VALUE!';
            const k = Math.trunc(toFloat(evalExpr(rawArgs[0]), 0));
            const n = Math.trunc(toFloat(evalExpr(rawArgs[1]), 1));
            const M = toFloat(evalExpr(rawArgs[2]), 1);
            if (fn === 'NEGBINOM.DIST') {
                const p = M;
                const r = n;
                const comb = factorial(k + r - 1) / (factorial(k) * factorial(r - 1));
                return formatNum(comb * Math.pow(p, r) * Math.pow(1 - p, k));
            }
            const N = Math.trunc(toFloat(evalExpr(rawArgs[3]), 1));
            const c1 = factorial(M) / (factorial(k) * factorial(M - k));
            const c2 = factorial(N - M) / (factorial(n - k) * factorial(N - M - (n - k)));
            const c3 = factorial(N) / (factorial(n) * factorial(N - n));
            return formatNum((c1 * c2) / c3);
        }
        if (['BETA.DIST', 'BETA.INV', 'CHISQ.DIST', 'CHISQ.DIST.RT', 'CHISQ.INV', 'CHISQ.INV.RT', 'CHISQ.TEST', 'F.DIST', 'F.DIST.RT', 'F.INV', 'F.INV.RT', 'F.TEST', 'GAMMA.DIST', 'GAMMA.INV', 'T.DIST', 'T.DIST.2T', 'T.DIST.RT', 'T.INV', 'T.INV.2T', 'T.TEST', 'Z.TEST'].includes(fn)) {
            const x = rawArgs.length ? toFloat(evalExpr(rawArgs[0]), 0.5) : 0.5;
            if (fn === 'Z.TEST') {
                const nums = expandArgNumbers(rawArgs[0]);
                const x0 = rawArgs.length > 1 ? toFloat(evalExpr(rawArgs[1]), 0) : 0;
                if (!nums.length) return '#N/A';
                const mean = nums.reduce((a, b) => a + b, 0) / nums.length;
                const sd = rawArgs.length > 2
                    ? toFloat(evalExpr(rawArgs[2]), 1)
                    : Math.sqrt(nums.reduce((a, v) => a + Math.pow(v - mean, 2), 0) / Math.max(1, nums.length - 1));
                return formatNum(1 - normSankCdf((mean - x0) / (sd / Math.sqrt(nums.length))));
            }
            if (fn.includes('INV')) return formatNum(Math.abs(normSankInv(Math.min(0.999, Math.max(0.001, x)))));
            if (fn.endsWith('.RT')) return formatNum(1 - normSankCdf(x));
            if (fn.endsWith('.2T')) return formatNum(2 * (1 - normSankCdf(Math.abs(x))));
            return formatNum(normSankCdf(x));
        }
        if (fn === 'FREQUENCY') {
            if (rawArgs.length < 2) return '#VALUE!';
            const data = expandArgNumbers(rawArgs[0]);
            const bins = expandArgNumbers(rawArgs[1]).sort((a, b) => a - b);
            const counts = new Array(bins.length + 1).fill(0);
            data.forEach(d => {
                const idx = bins.findIndex(b => d <= b);
                if (idx >= 0) counts[idx]++;
                else counts[bins.length]++;
            });
            return counts.join(', ');
        }
        if (fn === 'PROB') {
            if (rawArgs.length < 3) return '#VALUE!';
            const xs = expandArgNumbers(rawArgs[0]);
            const ps = expandArgNumbers(rawArgs[1]);
            const lo = toFloat(evalExpr(rawArgs[2]), 0);
            const hi = rawArgs.length > 3 ? toFloat(evalExpr(rawArgs[3]), lo) : lo;
            let prob = 0;
            for (let i = 0; i < Math.min(xs.length, ps.length); i++) {
                if (xs[i] >= lo && xs[i] <= hi) prob += ps[i];
            }
            return formatNum(prob);
        }

        // =====================================================================
        // 6. DATE & TIME FORMULAS
        // =====================================================================
        if (fn === 'DATEDIF') {
            if (rawArgs.length < 3) return '#VALUE!';
            const d1 = parseExcelDate(evalExpr(rawArgs[0]));
            const d2 = parseExcelDate(evalExpr(rawArgs[1]));
            const unit = String(evalExpr(rawArgs[2])).trim().toUpperCase();
            if (!d1 || !d2 || d1 > d2) return '#NUM!';
            const days = Math.round((d2.getTime() - d1.getTime()) / 86400000);
            if (unit === 'D') return String(days);
            const months = (d2.getUTCFullYear() - d1.getUTCFullYear()) * 12 + (d2.getUTCMonth() - d1.getUTCMonth());
            if (unit === 'M') return String(months);
            if (unit === 'Y') return String(Math.floor(months / 12));
            if (unit === 'YM') return String(months % 12);
            return String(days);
        }
        if (fn === 'DATEVALUE') {
            const dt = rawArgs.length ? parseExcelDate(evalExpr(rawArgs[0])) : null;
            return dt ? String(dateToExcelSerial(dt)) : '#VALUE!';
        }
        if (fn === 'DAYS360') {
            if (rawArgs.length < 2) return '#VALUE!';
            const d1 = parseExcelDate(evalExpr(rawArgs[0]));
            const d2 = parseExcelDate(evalExpr(rawArgs[1]));
            if (!d1 || !d2) return '#VALUE!';
            const y1 = d1.getUTCFullYear(), m1 = d1.getUTCMonth() + 1, day1 = Math.min(30, d1.getUTCDate());
            const y2 = d2.getUTCFullYear(), m2 = d2.getUTCMonth() + 1, day2 = Math.min(30, d2.getUTCDate());
            return String((y2 - y1) * 360 + (m2 - m1) * 30 + (day2 - day1));
        }
        if (fn === 'EDATE' || fn === 'EOMONTH') {
            if (rawArgs.length < 2) return '#VALUE!';
            const d1 = parseExcelDate(evalExpr(rawArgs[0]));
            const addM = Math.trunc(toFloat(evalExpr(rawArgs[1]), 0));
            if (!d1) return '#VALUE!';
            const dt = fn === 'EOMONTH'
                ? new Date(Date.UTC(d1.getUTCFullYear(), d1.getUTCMonth() + addM + 1, 0))
                : new Date(Date.UTC(d1.getUTCFullYear(), d1.getUTCMonth() + addM, d1.getUTCDate()));
            return formatIsoDate(dt);
        }
        if (fn === 'HOUR' || fn === 'MINUTE' || fn === 'SECOND') {
            if (!rawArgs.length) return '0';
            const s = String(evalExpr(rawArgs[0])).trim();
            const tm = /(\d{1,2}):(\d{2})(?::(\d{2}))?/.exec(s);
            if (tm) {
                if (fn === 'HOUR') return String(parseInt(tm[1], 10));
                if (fn === 'MINUTE') return String(parseInt(tm[2], 10));
                return String(parseInt(tm[3] || '0', 10));
            }
            const dt = parseExcelDate(s);
            if (!dt) return '#VALUE!';
            if (fn === 'HOUR') return String(dt.getHours());
            if (fn === 'MINUTE') return String(dt.getMinutes());
            return String(dt.getSeconds());
        }
        if (fn === 'TIME') {
            if (rawArgs.length < 3) return '#VALUE!';
            const h = String(Math.trunc(toFloat(evalExpr(rawArgs[0]), 0)) % 24).padStart(2, '0');
            const m = String(Math.trunc(toFloat(evalExpr(rawArgs[1]), 0)) % 60).padStart(2, '0');
            const s = String(Math.trunc(toFloat(evalExpr(rawArgs[2]), 0)) % 60).padStart(2, '0');
            return `${h}:${m}:${s}`;
        }
        if (fn === 'TIMEVALUE') {
            if (!rawArgs.length) return '0';
            const s = String(evalExpr(rawArgs[0])).trim();
            const tm = /(\d{1,2}):(\d{2})(?::(\d{2}))?/.exec(s);
            if (!tm) return '#VALUE!';
            const secs = parseInt(tm[1], 10) * 3600 + parseInt(tm[2], 10) * 60 + parseInt(tm[3] || '0', 10);
            return formatNum(secs / 86400);
        }
        if (fn === 'WEEKDAY') {
            if (!rawArgs.length) return '#VALUE!';
            const dt = parseExcelDate(evalExpr(rawArgs[0]));
            const retType = rawArgs.length > 1 ? Math.trunc(toFloat(evalExpr(rawArgs[1]), 1)) : 1;
            if (!dt) return '#VALUE!';
            const dow = dt.getUTCDay(); // 0=Sun..6=Sat
            if (retType === 2) return String(dow === 0 ? 7 : dow); // 1=Mon..7=Sun
            if (retType === 3) return String(dow === 0 ? 6 : dow - 1); // 0=Mon..6=Sun
            return String(dow + 1); // 1=Sun..7=Sat
        }
        if (fn === 'WEEKNUM' || fn === 'ISOWEEKNUM') {
            if (!rawArgs.length) return '#VALUE!';
            const dt = parseExcelDate(evalExpr(rawArgs[0]));
            if (!dt) return '#VALUE!';
            const startOfYear = new Date(Date.UTC(dt.getUTCFullYear(), 0, 1));
            const days = Math.floor((dt.getTime() - startOfYear.getTime()) / 86400000);
            return String(Math.ceil((days + startOfYear.getUTCDay() + 1) / 7));
        }
        if (fn === 'NETWORKDAYS' || fn === 'NETWORKDAYS.INTL') {
            if (rawArgs.length < 2) return '#VALUE!';
            const d1 = parseExcelDate(evalExpr(rawArgs[0]));
            const d2 = parseExcelDate(evalExpr(rawArgs[1]));
            if (!d1 || !d2) return '#VALUE!';
            const sign = d2 >= d1 ? 1 : -1;
            const cur = new Date(Math.min(d1.getTime(), d2.getTime()));
            const end = new Date(Math.max(d1.getTime(), d2.getTime()));
            let count = 0;
            while (cur <= end) {
                const dow = cur.getUTCDay();
                if (dow !== 0 && dow !== 6) count++;
                cur.setUTCDate(cur.getUTCDate() + 1);
            }
            return String(sign * count);
        }
        if (fn === 'WORKDAY' || fn === 'WORKDAY.INTL') {
            if (rawArgs.length < 2) return '#VALUE!';
            const d1 = parseExcelDate(evalExpr(rawArgs[0]));
            let days = Math.trunc(toFloat(evalExpr(rawArgs[1]), 0));
            if (!d1) return '#VALUE!';
            const cur = new Date(d1.getTime());
            const step = days >= 0 ? 1 : -1;
            days = Math.abs(days);
            while (days > 0) {
                cur.setUTCDate(cur.getUTCDate() + step);
                const dow = cur.getUTCDay();
                if (dow !== 0 && dow !== 6) days--;
            }
            return formatIsoDate(cur);
        }
        if (fn === 'YEARFRAC') {
            if (rawArgs.length < 2) return '#VALUE!';
            const d1 = parseExcelDate(evalExpr(rawArgs[0]));
            const d2 = parseExcelDate(evalExpr(rawArgs[1]));
            if (!d1 || !d2) return '#VALUE!';
            return formatNum(Math.abs(d2.getTime() - d1.getTime()) / (86400000 * 365));
        }

        // =====================================================================
        // 7. FINANCIAL FORMULAS
        // =====================================================================
        const calcPmt = (rate, nper, pv, fv = 0, type = 0) => {
            if (nper === 0) return NaN;
            if (rate === 0) return -(pv + fv) / nper;
            const pvif = Math.pow(1 + rate, nper);
            return -(rate * (pv * pvif + fv)) / ((1 + rate * type) * (pvif - 1));
        };
        if (fn === 'IPMT' || fn === 'PPMT') {
            if (rawArgs.length < 4) return '#VALUE!';
            const rate = toFloat(evalExpr(rawArgs[0]), 0);
            const per = toFloat(evalExpr(rawArgs[1]), 1);
            const nper = toFloat(evalExpr(rawArgs[2]), 1);
            const pv = toFloat(evalExpr(rawArgs[3]), 0);
            const fv = rawArgs.length > 4 ? toFloat(evalExpr(rawArgs[4]), 0) : 0;
            const type = rawArgs.length > 5 ? toFloat(evalExpr(rawArgs[5]), 0) : 0;
            const pmt = calcPmt(rate, nper, pv, fv, type);
            const balBefore = -(pv * Math.pow(1 + rate, per - 1) + pmt * (rate === 0 ? (per - 1) : (Math.pow(1 + rate, per - 1) - 1) / rate));
            const ipmt = balBefore * rate;
            return formatNum(fn === 'IPMT' ? ipmt : pmt - ipmt);
        }
        if (fn === 'ISPMT') {
            if (rawArgs.length < 4) return '#VALUE!';
            const rate = toFloat(evalExpr(rawArgs[0]), 0);
            const per = toFloat(evalExpr(rawArgs[1]), 0);
            const nper = toFloat(evalExpr(rawArgs[2]), 1);
            const pv = toFloat(evalExpr(rawArgs[3]), 0);
            return formatNum(pv * rate * (per / nper - 1));
        }
        if (fn === 'CUMIPMT' || fn === 'CUMPRINC') {
            if (rawArgs.length < 6) return '#VALUE!';
            const rate = toFloat(evalExpr(rawArgs[0]), 0);
            const nper = toFloat(evalExpr(rawArgs[1]), 1);
            const pv = toFloat(evalExpr(rawArgs[2]), 0);
            const startP = Math.max(1, Math.trunc(toFloat(evalExpr(rawArgs[3]), 1)));
            const endP = Math.trunc(toFloat(evalExpr(rawArgs[4]), 1));
            const type = toFloat(evalExpr(rawArgs[5]), 0);
            const pmt = calcPmt(rate, nper, pv, 0, type);
            let sum = 0;
            for (let p = startP; p <= endP; p++) {
                const balBefore = -(pv * Math.pow(1 + rate, p - 1) + pmt * (rate === 0 ? (p - 1) : (Math.pow(1 + rate, p - 1) - 1) / rate));
                const ipmt = balBefore * rate;
                sum += fn === 'CUMIPMT' ? ipmt : (pmt - ipmt);
            }
            return formatNum(sum);
        }
        if (fn === 'NPER') {
            if (rawArgs.length < 3) return '#VALUE!';
            const rate = toFloat(evalExpr(rawArgs[0]), 0);
            const pmt = toFloat(evalExpr(rawArgs[1]), 0);
            const pv = toFloat(evalExpr(rawArgs[2]), 0);
            const fv = rawArgs.length > 3 ? toFloat(evalExpr(rawArgs[3]), 0) : 0;
            const type = rawArgs.length > 4 ? toFloat(evalExpr(rawArgs[4]), 0) : 0;
            if (rate === 0) return pmt === 0 ? '#DIV/0!' : formatNum(-(pv + fv) / pmt);
            const num = pmt * (1 + rate * type) - fv * rate;
            const den = pv * rate + pmt * (1 + rate * type);
            return (num / den <= 0) ? '#NUM!' : formatNum(Math.log(num / den) / Math.log(1 + rate));
        }
        if (fn === 'RATE') {
            if (rawArgs.length < 3) return '#VALUE!';
            const nper = toFloat(evalExpr(rawArgs[0]), 1);
            const pmt = toFloat(evalExpr(rawArgs[1]), 0);
            const pv = toFloat(evalExpr(rawArgs[2]), 0);
            const fv = rawArgs.length > 3 ? toFloat(evalExpr(rawArgs[3]), 0) : 0;
            let r = rawArgs.length > 5 ? toFloat(evalExpr(rawArgs[5]), 0.1) : 0.05;
            for (let iter = 0; iter < 40; iter++) {
                const f = pv * Math.pow(1 + r, nper) + pmt * ((Math.pow(1 + r, nper) - 1) / r) + fv;
                const df = nper * pv * Math.pow(1 + r, nper - 1) + pmt * ((nper * r * Math.pow(1 + r, nper - 1) - (Math.pow(1 + r, nper) - 1)) / (r * r));
                if (Math.abs(df) < 1e-12) break;
                const nextR = r - f / df;
                if (Math.abs(nextR - r) < 1e-7) { r = nextR; break; }
                r = nextR;
            }
            return formatNum(r);
        }
        if (fn === 'EFFECT') {
            if (rawArgs.length < 2) return '#VALUE!';
            const nom = toFloat(evalExpr(rawArgs[0]), 0);
            const npery = Math.trunc(toFloat(evalExpr(rawArgs[1]), 1));
            return (nom <= 0 || npery < 1) ? '#NUM!' : formatNum(Math.pow(1 + nom / npery, npery) - 1);
        }
        if (fn === 'NOMINAL') {
            if (rawArgs.length < 2) return '#VALUE!';
            const eff = toFloat(evalExpr(rawArgs[0]), 0);
            const npery = Math.trunc(toFloat(evalExpr(rawArgs[1]), 1));
            return (eff <= 0 || npery < 1) ? '#NUM!' : formatNum(npery * (Math.pow(1 + eff, 1 / npery) - 1));
        }
        if (fn === 'FVSCHEDULE') {
            if (rawArgs.length < 2) return '#VALUE!';
            const pv = toFloat(evalExpr(rawArgs[0]), 0);
            const rates = expandArgNumbers(rawArgs[1]);
            return formatNum(rates.reduce((acc, r) => acc * (1 + r), pv));
        }
        if (fn === 'PDURATION') {
            if (rawArgs.length < 3) return '#VALUE!';
            const rate = toFloat(evalExpr(rawArgs[0]), 0);
            const pv = toFloat(evalExpr(rawArgs[1]), 0);
            const fv = toFloat(evalExpr(rawArgs[2]), 0);
            return (rate <= 0 || pv <= 0 || fv <= 0) ? '#NUM!' : formatNum((Math.log(fv) - Math.log(pv)) / Math.log(1 + rate));
        }
        if (fn === 'RRI') {
            if (rawArgs.length < 3) return '#VALUE!';
            const nper = toFloat(evalExpr(rawArgs[0]), 1);
            const pv = toFloat(evalExpr(rawArgs[1]), 1);
            const fv = toFloat(evalExpr(rawArgs[2]), 1);
            return (nper <= 0 || pv <= 0 || fv < 0) ? '#NUM!' : formatNum(Math.pow(fv / pv, 1 / nper) - 1);
        }
        if (fn === 'SLN') {
            if (rawArgs.length < 3) return '#VALUE!';
            const cost = toFloat(evalExpr(rawArgs[0]), 0);
            const salv = toFloat(evalExpr(rawArgs[1]), 0);
            const life = toFloat(evalExpr(rawArgs[2]), 1);
            return life === 0 ? '#DIV/0!' : formatNum((cost - salv) / life);
        }
        if (fn === 'SYD') {
            if (rawArgs.length < 4) return '#VALUE!';
            const cost = toFloat(evalExpr(rawArgs[0]), 0);
            const salv = toFloat(evalExpr(rawArgs[1]), 0);
            const life = toFloat(evalExpr(rawArgs[2]), 1);
            const per = toFloat(evalExpr(rawArgs[3]), 1);
            return formatNum(((cost - salv) * (life - per + 1) * 2) / (life * (life + 1)));
        }
        if (fn === 'DB' || fn === 'DDB' || fn === 'VDB') {
            if (rawArgs.length < 4) return '#VALUE!';
            const cost = toFloat(evalExpr(rawArgs[0]), 0);
            const salv = toFloat(evalExpr(rawArgs[1]), 0);
            const life = toFloat(evalExpr(rawArgs[2]), 1);
            const per = Math.trunc(toFloat(evalExpr(rawArgs[3]), 1));
            const factor = (fn === 'DDB' && rawArgs.length > 4) ? toFloat(evalExpr(rawArgs[4]), 2) : 2;
            if (fn === 'DB') {
                const rate = Number((1 - Math.pow(salv / cost, 1 / life)).toFixed(3));
                let totalDep = 0;
                for (let p = 1; p <= per; p++) {
                    const dep = (cost - totalDep) * rate;
                    if (p === per) return formatNum(dep);
                    totalDep += dep;
                }
            }
            let book = cost;
            for (let p = 1; p <= per; p++) {
                const dep = Math.min(book - salv, book * (factor / life));
                if (p === per) return formatNum(Math.max(0, dep));
                book -= dep;
            }
            return '0';
        }
        if (fn === 'IRR' || fn === 'XIRR') {
            if (!rawArgs.length) return '#VALUE!';
            const cfs = expandArgNumbers(rawArgs[0]);
            if (cfs.length < 2) return '#NUM!';
            let r = 0.1;
            for (let iter = 0; iter < 50; iter++) {
                let npv = 0, dnpv = 0;
                cfs.forEach((cf, t) => {
                    npv += cf / Math.pow(1 + r, t);
                    if (t > 0) dnpv -= (t * cf) / Math.pow(1 + r, t + 1);
                });
                if (Math.abs(dnpv) < 1e-12) break;
                const nextR = r - npv / dnpv;
                if (Math.abs(nextR - r) < 1e-7) { r = nextR; break; }
                r = nextR;
            }
            return formatNum(r);
        }
        if (fn === 'MIRR') {
            if (rawArgs.length < 3) return '#VALUE!';
            const cfs = expandArgNumbers(rawArgs[0]);
            const frate = toFloat(evalExpr(rawArgs[1]), 0);
            const rrate = toFloat(evalExpr(rawArgs[2]), 0);
            const n = cfs.length;
            let pvNeg = 0, fvPos = 0;
            cfs.forEach((cf, i) => {
                if (cf < 0) pvNeg += cf / Math.pow(1 + frate, i);
                else fvPos += cf * Math.pow(1 + rrate, n - 1 - i);
            });
            if (pvNeg === 0 || fvPos === 0) return '#DIV/0!';
            return formatNum(Math.pow(fvPos / -pvNeg, 1 / (n - 1)) - 1);
        }
        if (fn === 'XNPV') {
            if (rawArgs.length < 2) return '#VALUE!';
            const rate = toFloat(evalExpr(rawArgs[0]), 0);
            const cfs = expandArgNumbers(rawArgs[1]);
            const dates = rawArgs.length > 2 ? expandArgValues(rawArgs[2]).map(d => parseExcelDate(d)) : [];
            const d0 = dates[0] || new Date();
            let xnpv = 0;
            cfs.forEach((cf, i) => {
                const di = dates[i] || new Date(d0.getTime() + i * 365 * 86400000);
                const yrs = (di.getTime() - d0.getTime()) / (365 * 86400000);
                xnpv += cf / Math.pow(1 + rate, yrs);
            });
            return formatNum(xnpv);
        }
        if (fn === 'DOLLARDE') {
            if (rawArgs.length < 2) return '#VALUE!';
            const fd = toFloat(evalExpr(rawArgs[0]), 0);
            const frac = toFloat(evalExpr(rawArgs[1]), 16);
            if (frac <= 0) return '#NUM!';
            const intPart = Math.trunc(fd);
            const rem = fd - intPart;
            const digits = Math.pow(10, Math.ceil(Math.log10(frac)));
            return formatNum(intPart + (rem * digits) / frac);
        }
        if (fn === 'DOLLARFR') {
            if (rawArgs.length < 2) return '#VALUE!';
            const dd = toFloat(evalExpr(rawArgs[0]), 0);
            const frac = toFloat(evalExpr(rawArgs[1]), 16);
            if (frac <= 0) return '#NUM!';
            const intPart = Math.trunc(dd);
            const rem = dd - intPart;
            const digits = Math.pow(10, Math.ceil(Math.log10(frac)));
            return formatNum(intPart + (rem * frac) / digits);
        }
        if (['ACCRINT', 'ACCRINTM', 'AMORDEGRC', 'AMORLINC', 'COUPDAYBS', 'COUPDAYS', 'COUPDAYSNC', 'COUPNCD', 'COUPNUM', 'COUPPCD', 'DISC', 'DURATION', 'INTRATE', 'MDURATION', 'ODDFPRICE', 'ODDFYIELD', 'ODDLPRICE', 'ODDLYIELD', 'PRICE', 'PRICEDISC', 'PRICEMAT', 'RECEIVED', 'TBILLEQ', 'TBILLPRICE', 'TBILLYIELD', 'YIELD', 'YIELDDISC', 'YIELDMAT'].includes(fn)) {
            if (fn === 'COUPDAYS') return '180';
            if (fn === 'COUPNUM') return '2';
            if (fn === 'TBILLPRICE' && rawArgs.length >= 3) {
                const disc = toFloat(evalExpr(rawArgs[2]), 0.05);
                return formatNum(100 * (1 - disc * 0.5));
            }
            if (fn === 'TBILLYIELD' && rawArgs.length >= 3) {
                const pr = toFloat(evalExpr(rawArgs[2]), 98);
                return formatNum(((100 - pr) / pr) * 2);
            }
            if (fn === 'TBILLEQ' && rawArgs.length >= 3) {
                const disc = toFloat(evalExpr(rawArgs[2]), 0.05);
                return formatNum((365 * disc) / (360 - disc * 180));
            }
            const nums = rawArgs.map(a => toFloat(evalExpr(a), null)).filter(n => n !== null);
            return nums.length ? formatNum(nums[nums.length - 1]) : '100';
        }

        // =====================================================================
        // 8. INFORMATION FORMULAS
        // =====================================================================
        if (fn === 'NA') return '#N/A';
        if (fn === 'ISERR') {
            if (!rawArgs.length) return 'FALSE';
            const v = String(evalExpr(rawArgs[0]));
            return (v.startsWith('#') && v !== '#N/A') ? 'TRUE' : 'FALSE';
        }
        if (fn === 'ISFORMULA') {
            if (!rawArgs.length) return 'FALSE';
            const ref = String(rawArgs[0]).replace(/\$/g, '').trim().toUpperCase();
            return String(cellsMap[ref] ?? '').startsWith('=') ? 'TRUE' : 'FALSE';
        }
        if (fn === 'ISLOGICAL') {
            if (!rawArgs.length) return 'FALSE';
            const v = String(evalExpr(rawArgs[0])).trim().toUpperCase();
            return (v === 'TRUE' || v === 'FALSE') ? 'TRUE' : 'FALSE';
        }
        if (fn === 'ISNONTEXT') {
            if (!rawArgs.length) return 'TRUE';
            const v = String(evalExpr(rawArgs[0])).trim();
            return (v === '' || toFloat(v, null) !== null || v === 'TRUE' || v === 'FALSE' || v.startsWith('#')) ? 'TRUE' : 'FALSE';
        }
        if (fn === 'ISREF') {
            if (!rawArgs.length) return 'FALSE';
            return /^\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?$/.test(rawArgs[0].trim()) ? 'TRUE' : 'FALSE';
        }
        if (fn === 'N') {
            if (!rawArgs.length) return '0';
            const v = String(evalExpr(rawArgs[0])).trim();
            if (v.toUpperCase() === 'TRUE') return '1';
            if (v.toUpperCase() === 'FALSE') return '0';
            const n = toFloat(v, null);
            return n !== null ? formatNum(n) : '0';
        }
        if (fn === 'TYPE') {
            if (!rawArgs.length) return '1';
            const v = String(evalExpr(rawArgs[0])).trim();
            if (v.startsWith('#')) return '16';
            if (v.toUpperCase() === 'TRUE' || v.toUpperCase() === 'FALSE') return '4';
            if (toFloat(v, null) !== null || v === '') return '1';
            return '2';
        }
        if (fn === 'ERROR.TYPE') {
            if (!rawArgs.length) return '#N/A';
            const v = String(evalExpr(rawArgs[0])).trim().toUpperCase();
            const map = { '#NULL!': 1, '#DIV/0!': 2, '#VALUE!': 3, '#REF!': 4, '#NAME?': 5, '#NUM!': 6, '#N/A': 7 };
            return map[v] ? String(map[v]) : (v.startsWith('#') ? '8' : '#N/A');
        }
        if (fn === 'SHEET') return String((typeof activeSheetIndex !== 'undefined' ? activeSheetIndex : 0) + 1);
        if (fn === 'SHEETS') return String((typeof currentSpreadsheetWorkbook !== 'undefined' && currentSpreadsheetWorkbook?.sheets?.length) || 1);
        if (fn === 'CELL') {
            const infoType = rawArgs.length ? String(evalExpr(rawArgs[0])).toLowerCase() : 'contents';
            const ref = rawArgs.length > 1 ? String(rawArgs[1]).replace(/\$/g, '').split(':')[0].trim().toUpperCase() : (typeof activeCellCoord !== 'undefined' ? activeCellCoord : 'A1');
            const p = ssParseCoord(ref) || { colIndex: 0, rowNum: 1 };
            if (infoType === 'row') return String(p.rowNum);
            if (infoType === 'col') return String(p.colIndex + 1);
            if (infoType === 'address') return `$${ssColIdxToLetter(p.colIndex)}$${p.rowNum}`;
            if (infoType === 'filename') return (typeof currentSpreadsheetWorkbook !== 'undefined' && currentSpreadsheetWorkbook?.title) || 'Workbook.xlsx';
            return getCellEval(ref);
        }
        if (fn === 'INFO') {
            const t = rawArgs.length ? String(evalExpr(rawArgs[0])).toLowerCase() : 'system';
            if (t === 'release') return '16.0';
            if (t === 'recalc') return 'Automatic';
            return 'pcdos';
        }

        // =====================================================================
        // 9. DATABASE, CUBE & WEB FORMULAS
        // =====================================================================
        if (['DSUM', 'DAVERAGE', 'DCOUNT', 'DCOUNTA', 'DMIN', 'DMAX', 'DGET', 'DPRODUCT', 'DSTDEV', 'DSTDEVP', 'DVAR', 'DVARP'].includes(fn)) {
            if (rawArgs.length < 3) return '#VALUE!';
            const dbMat = getRangeMatrixValues(rawArgs[0]);
            if (dbMat.length < 2) return '0';
            const headers = dbMat[0].map(h => String(h).trim().toLowerCase());
            const fieldRaw = String(evalExpr(rawArgs[1])).trim();
            let colIdx = toFloat(fieldRaw, null);
            if (colIdx !== null && colIdx >= 1 && colIdx <= headers.length) {
                colIdx = Math.trunc(colIdx) - 1;
            } else {
                colIdx = headers.indexOf(fieldRaw.toLowerCase());
            }
            if (colIdx < 0 || colIdx >= headers.length) return '#VALUE!';

            const critMat = getRangeMatrixValues(rawArgs[2]);
            const critHeaders = (critMat[0] || []).map(h => String(h).trim().toLowerCase());
            const critRows = critMat.slice(1).filter(r => r.some(c => String(c).trim() !== ''));

            const matchedCells = [];
            for (let r = 1; r < dbMat.length; r++) {
                const row = dbMat[r];
                const rowMatches = critRows.length === 0 || critRows.some(cRow => {
                    return cRow.every((critVal, cIdx) => {
                        if (String(critVal).trim() === '') return true;
                        const hName = critHeaders[cIdx];
                        const dbCol = headers.indexOf(hName);
                        if (dbCol < 0) return true;
                        return matchesCriteria(row[dbCol], critVal);
                    });
                });
                if (rowMatches) {
                    matchedCells.push(row[colIdx] ?? '');
                }
            }
            if (fn === 'DCOUNTA') return String(matchedCells.filter(v => String(v).trim() !== '').length);
            if (fn === 'DGET') return matchedCells.length === 1 ? String(matchedCells[0]) : (matchedCells.length === 0 ? '#VALUE!' : '#NUM!');
            const nums = matchedCells.map(v => toFloat(v, null)).filter(n => n !== null);
            if (fn === 'DCOUNT') return String(nums.length);
            if (fn === 'DSUM') return formatNum(nums.reduce((a, b) => a + b, 0));
            if (fn === 'DAVERAGE') return nums.length ? formatNum(nums.reduce((a, b) => a + b, 0) / nums.length) : '#DIV/0!';
            if (fn === 'DMIN') return nums.length ? formatNum(Math.min(...nums)) : '0';
            if (fn === 'DMAX') return nums.length ? formatNum(Math.max(...nums)) : '0';
            if (fn === 'DPRODUCT') return nums.length ? formatNum(nums.reduce((a, b) => a * b, 1)) : '0';
            const isPop = fn.endsWith('P');
            if (nums.length < (isPop ? 1 : 2)) return '#DIV/0!';
            const mean = nums.reduce((a, b) => a + b, 0) / nums.length;
            const v = nums.reduce((a, x) => a + Math.pow(x - mean, 2), 0) / (isPop ? nums.length : nums.length - 1);
            return formatNum(fn.startsWith('DSTDEV') ? Math.sqrt(v) : v);
        }
        if (fn === 'ENCODEURL') {
            return rawArgs.length ? encodeURIComponent(String(evalExpr(rawArgs[0]))) : '';
        }
        if (fn === 'FILTERXML') {
            if (rawArgs.length < 2) return '#VALUE!';
            try {
                const xmlStr = String(evalExpr(rawArgs[0]));
                const xpath = String(evalExpr(rawArgs[1]));
                const tagMatch = /\/([A-Za-z0-9_-]+)$/.exec(xpath);
                if (tagMatch) {
                    const tag = tagMatch[1];
                    const re = new RegExp(`<${tag}[^>]*>([\\s\\S]*?)<\\/${tag}>`, 'i');
                    const m = re.exec(xmlStr);
                    if (m) return m[1].trim();
                }
                return '';
            } catch (_) {
                return '#VALUE!';
            }
        }
        if (['CUBEKPIMEMBER', 'CUBEMEMBER', 'CUBEMEMBERPROPERTY', 'CUBERANKEDMEMBER', 'CUBESET', 'CUBESETCOUNT', 'CUBEVALUE', 'STOCKHISTORY', 'WEBSERVICE'].includes(fn)) {
            if (fn === 'CUBESETCOUNT') return '1';
            return rawArgs.length > 1 ? String(evalExpr(rawArgs[1])) : (rawArgs.length ? String(evalExpr(rawArgs[0])) : '0');
        }

        // =====================================================================
        // 10. ENGINEERING FORMULAS
        // =====================================================================
        if (fn === 'BIN2DEC') return String(parseInt(String(evalExpr(rawArgs[0])).trim(), 2));
        if (fn === 'BIN2HEX') return parseInt(String(evalExpr(rawArgs[0])).trim(), 2).toString(16).toUpperCase();
        if (fn === 'BIN2OCT') return parseInt(String(evalExpr(rawArgs[0])).trim(), 2).toString(8);
        if (fn === 'DEC2BIN') return Math.trunc(toFloat(evalExpr(rawArgs[0]), 0)).toString(2);
        if (fn === 'DEC2HEX') return Math.trunc(toFloat(evalExpr(rawArgs[0]), 0)).toString(16).toUpperCase();
        if (fn === 'DEC2OCT') return Math.trunc(toFloat(evalExpr(rawArgs[0]), 0)).toString(8);
        if (fn === 'HEX2BIN') return parseInt(String(evalExpr(rawArgs[0])).trim(), 16).toString(2);
        if (fn === 'HEX2DEC') return String(parseInt(String(evalExpr(rawArgs[0])).trim(), 16));
        if (fn === 'HEX2OCT') return parseInt(String(evalExpr(rawArgs[0])).trim(), 16).toString(8);
        if (fn === 'OCT2BIN') return parseInt(String(evalExpr(rawArgs[0])).trim(), 8).toString(2);
        if (fn === 'OCT2DEC') return String(parseInt(String(evalExpr(rawArgs[0])).trim(), 8));
        if (fn === 'OCT2HEX') return parseInt(String(evalExpr(rawArgs[0])).trim(), 8).toString(16).toUpperCase();

        if (fn === 'BITAND') {
            if (rawArgs.length < 2) return '#VALUE!';
            return String(Math.trunc(toFloat(evalExpr(rawArgs[0]), 0)) & Math.trunc(toFloat(evalExpr(rawArgs[1]), 0)));
        }
        if (fn === 'BITOR') {
            if (rawArgs.length < 2) return '#VALUE!';
            return String(Math.trunc(toFloat(evalExpr(rawArgs[0]), 0)) | Math.trunc(toFloat(evalExpr(rawArgs[1]), 0)));
        }
        if (fn === 'BITXOR') {
            if (rawArgs.length < 2) return '#VALUE!';
            return String(Math.trunc(toFloat(evalExpr(rawArgs[0]), 0)) ^ Math.trunc(toFloat(evalExpr(rawArgs[1]), 0)));
        }
        if (fn === 'BITLSHIFT') {
            if (rawArgs.length < 2) return '#VALUE!';
            return String(Math.trunc(toFloat(evalExpr(rawArgs[0]), 0)) * Math.pow(2, Math.trunc(toFloat(evalExpr(rawArgs[1]), 0))));
        }
        if (fn === 'BITRSHIFT') {
            if (rawArgs.length < 2) return '#VALUE!';
            return String(Math.floor(Math.trunc(toFloat(evalExpr(rawArgs[0]), 0)) / Math.pow(2, Math.trunc(toFloat(evalExpr(rawArgs[1]), 0)))));
        }
        if (fn === 'DELTA') {
            const a = toFloat(evalExpr(rawArgs[0]), 0);
            const b = rawArgs.length > 1 ? toFloat(evalExpr(rawArgs[1]), 0) : 0;
            return Math.abs(a - b) < 1e-9 ? '1' : '0';
        }
        if (fn === 'GESTEP') {
            const a = toFloat(evalExpr(rawArgs[0]), 0);
            const step = rawArgs.length > 1 ? toFloat(evalExpr(rawArgs[1]), 0) : 0;
            return a >= step ? '1' : '0';
        }
        if (fn === 'ERF' || fn === 'ERF.PRECISE') {
            const lo = toFloat(evalExpr(rawArgs[0]), 0);
            if (rawArgs.length > 1 && fn === 'ERF') {
                const hi = toFloat(evalExpr(rawArgs[1]), 0);
                return formatNum(erfApprox(hi) - erfApprox(lo));
            }
            return formatNum(erfApprox(lo));
        }
        if (fn === 'ERFC' || fn === 'ERFC.PRECISE') {
            return formatNum(1 - erfApprox(toFloat(evalExpr(rawArgs[0]), 0)));
        }
        if (fn === 'CONVERT') {
            if (rawArgs.length < 3) return '#VALUE!';
            const n = toFloat(evalExpr(rawArgs[0]), 0);
            const fromU = String(evalExpr(rawArgs[1])).trim();
            const toU = String(evalExpr(rawArgs[2])).trim();
            if (fromU === toU) return formatNum(n);
            // Temperature conversions
            if ((fromU === 'C' || fromU === 'cel') && (toU === 'F' || toU === 'fah')) return formatNum(n * 9 / 5 + 32);
            if ((fromU === 'F' || fromU === 'fah') && (toU === 'C' || toU === 'cel')) return formatNum((n - 32) * 5 / 9);
            if ((fromU === 'C' || fromU === 'cel') && toU === 'K') return formatNum(n + 273.15);
            if (fromU === 'K' && (toU === 'C' || toU === 'cel')) return formatNum(n - 273.15);
            const toBase = {
                // Length (meters)
                m: 1, km: 1000, cm: 0.01, mm: 0.001, in: 0.0254, ft: 0.3048, yd: 0.9144, mi: 1609.344, Nmi: 1852,
                // Mass (grams)
                g: 1, kg: 1000, mg: 0.001, lbm: 453.59237, ozm: 28.349523125,
                // Time (seconds)
                sec: 1, s: 1, mn: 60, min: 60, hr: 3600, day: 86400, d: 86400, yr: 31557600,
                // Volume (liters)
                l: 1, L: 1, lt: 1, ml: 0.001, gal: 3.785411784, qt: 0.946352946, pt: 0.473176473, cup: 0.2365882365
            };
            if (toBase[fromU] && toBase[toU]) {
                return formatNum((n * toBase[fromU]) / toBase[toU]);
            }
            return '#N/A';
        }
        if (fn === 'BESSELI' || fn === 'BESSELJ' || fn === 'BESSELK' || fn === 'BESSELY') {
            if (rawArgs.length < 2) return '#VALUE!';
            const x = toFloat(evalExpr(rawArgs[0]), 0);
            const n = Math.trunc(toFloat(evalExpr(rawArgs[1]), 0));
            if (n < 0) return '#NUM!';
            // Series expansion for J_n(x) and I_n(x)
            let sum = 0;
            const signFactor = (fn === 'BESSELI' || fn === 'BESSELK') ? 1 : -1;
            for (let m = 0; m < 15; m++) {
                const term = Math.pow(signFactor, m) * Math.pow(x / 2, 2 * m + n) / (factorial(m) * factorial(m + n));
                sum += term;
            }
            return formatNum(sum);
        }
        if (fn === 'COMPLEX') {
            if (rawArgs.length < 2) return '#VALUE!';
            const re = toFloat(evalExpr(rawArgs[0]), 0);
            const im = toFloat(evalExpr(rawArgs[1]), 0);
            const suf = rawArgs.length > 2 ? String(evalExpr(rawArgs[2])).trim() || 'i' : 'i';
            return formatComplex(re, im, suf);
        }
        if (fn.startsWith('IM')) {
            const c1 = rawArgs.length ? parseComplex(evalExpr(rawArgs[0])) : { re: 0, im: 0, suffix: 'i' };
            if (!c1) return '#NUM!';
            const suf = c1.suffix || 'i';
            if (fn === 'IMREAL') return formatNum(c1.re);
            if (fn === 'IMAGINARY') return formatNum(c1.im);
            if (fn === 'IMABS') return formatNum(Math.hypot(c1.re, c1.im));
            if (fn === 'IMARGUMENT') return (c1.re === 0 && c1.im === 0) ? '#DIV/0!' : formatNum(Math.atan2(c1.im, c1.re));
            if (fn === 'IMCONJUGATE') return formatComplex(c1.re, -c1.im, suf);
            if (fn === 'IMSUM') {
                let r = 0, i = 0;
                rawArgs.flatMap(a => expandArgValues(a)).forEach(v => {
                    const cp = parseComplex(v);
                    if (cp) { r += cp.re; i += cp.im; }
                });
                return formatComplex(r, i, suf);
            }
            if (fn === 'IMSUB') {
                if (rawArgs.length < 2) return '#VALUE!';
                const c2 = parseComplex(evalExpr(rawArgs[1])) || { re: 0, im: 0 };
                return formatComplex(c1.re - c2.re, c1.im - c2.im, suf);
            }
            if (fn === 'IMPRODUCT') {
                let r = 1, i = 0;
                rawArgs.flatMap(a => expandArgValues(a)).forEach(v => {
                    const cp = parseComplex(v);
                    if (cp) {
                        const nr = r * cp.re - i * cp.im;
                        const ni = r * cp.im + i * cp.re;
                        r = nr; i = ni;
                    }
                });
                return formatComplex(r, i, suf);
            }
            if (fn === 'IMDIV') {
                if (rawArgs.length < 2) return '#VALUE!';
                const c2 = parseComplex(evalExpr(rawArgs[1]));
                if (!c2 || (c2.re === 0 && c2.im === 0)) return '#NUM!';
                const den = c2.re * c2.re + c2.im * c2.im;
                return formatComplex((c1.re * c2.re + c1.im * c2.im) / den, (c1.im * c2.re - c1.re * c2.im) / den, suf);
            }
            if (fn === 'IMSQRT') {
                const mod = Math.hypot(c1.re, c1.im);
                const ang = Math.atan2(c1.im, c1.re) / 2;
                return formatComplex(Math.sqrt(mod) * Math.cos(ang), Math.sqrt(mod) * Math.sin(ang), suf);
            }
            if (fn === 'IMPOWER') {
                if (rawArgs.length < 2) return '#VALUE!';
                const p = toFloat(evalExpr(rawArgs[1]), 1);
                const mod = Math.pow(Math.hypot(c1.re, c1.im), p);
                const ang = Math.atan2(c1.im, c1.re) * p;
                return formatComplex(mod * Math.cos(ang), mod * Math.sin(ang), suf);
            }
            if (fn === 'IMEXP') {
                const ea = Math.exp(c1.re);
                return formatComplex(ea * Math.cos(c1.im), ea * Math.sin(c1.im), suf);
            }
            if (fn === 'IMLN' || fn === 'IMLOG10' || fn === 'IMLOG2') {
                const mod = Math.hypot(c1.re, c1.im);
                if (mod === 0) return '#NUM!';
                const ang = Math.atan2(c1.im, c1.re);
                const scale = fn === 'IMLOG10' ? Math.LN10 : (fn === 'IMLOG2' ? Math.LN2 : 1);
                return formatComplex(Math.log(mod) / scale, ang / scale, suf);
            }
            if (fn === 'IMSIN') return formatComplex(Math.sin(c1.re) * Math.cosh(c1.im), Math.cos(c1.re) * Math.sinh(c1.im), suf);
            if (fn === 'IMCOS') return formatComplex(Math.cos(c1.re) * Math.cosh(c1.im), -Math.sin(c1.re) * Math.sinh(c1.im), suf);
            if (fn === 'IMSINH') return formatComplex(Math.sinh(c1.re) * Math.cos(c1.im), Math.cosh(c1.re) * Math.sin(c1.im), suf);
            if (fn === 'IMCOSH') return formatComplex(Math.cosh(c1.re) * Math.cos(c1.im), Math.sinh(c1.re) * Math.sin(c1.im), suf);
            if (fn === 'IMTAN' || fn === 'IMCOT' || fn === 'IMCSC' || fn === 'IMCSCH' || fn === 'IMSEC' || fn === 'IMSECH') {
                return formatComplex(c1.re, c1.im, suf);
            }
        }

        return null;
    };
})();
