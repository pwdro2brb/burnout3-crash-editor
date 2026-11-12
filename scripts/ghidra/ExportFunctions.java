// Export selected analyzed functions, references, assembly and pseudocode.
// @category Burnout3
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import com.google.gson.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public class ExportFunctions extends GhidraScript {
    private String addr(Address a) { return a == null ? null : a.toString(); }
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Path out = Paths.get(args[0]); Files.createDirectories(out);
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        try {
            Set<Address> entries = new LinkedHashSet<>();
            for (int i = 1; i < args.length; ++i) {
                Function f = getFunctionContaining(toAddr(args[i]));
                if (f == null) { println("NO_ANALYZED_FUNCTION " + args[i]); continue; }
                if (!entries.add(f.getEntryPoint())) continue;
                monitor.checkCancelled();
                JsonObject root = new JsonObject();
                root.addProperty("requested_address", args[i]);
                root.addProperty("entry", addr(f.getEntryPoint()));
                root.addProperty("name", f.getName());
                root.addProperty("source_sha256", currentProgram.getExecutableSHA256());
                root.addProperty("language", currentProgram.getLanguageID().toString());
                root.addProperty("static_analysis_only", true);
                JsonArray ranges = new JsonArray();
                AddressRangeIterator rangeIterator = f.getBody().getAddressRanges();
                while (rangeIterator.hasNext()) {
                    AddressRange range = rangeIterator.next(); JsonObject row = new JsonObject();
                    row.addProperty("start", addr(range.getMinAddress())); row.addProperty("end_inclusive", addr(range.getMaxAddress())); ranges.add(row);
                }
                root.add("body_ranges", ranges);
                JsonArray insns = new JsonArray();
                InstructionIterator iterator = currentProgram.getListing().getInstructions(f.getBody(), true);
                int count = 0;
                while (iterator.hasNext() && count++ < 3000) {
                    Instruction insn = iterator.next(); JsonObject row = new JsonObject();
                    row.addProperty("address", addr(insn.getAddress())); row.addProperty("text", insn.toString());
                    row.addProperty("bytes", HexFormat.of().formatHex(insn.getBytes()));
                    JsonArray refs = new JsonArray();
                    for (Reference ref : insn.getReferencesFrom()) {
                        JsonObject r = new JsonObject(); r.addProperty("to", addr(ref.getToAddress()));
                        r.addProperty("type", ref.getReferenceType().toString()); refs.add(r);
                    }
                    row.add("references", refs); insns.add(row);
                }
                root.add("instructions", insns); root.addProperty("instructions_truncated", iterator.hasNext());
                JsonArray incoming = new JsonArray();
                ReferenceIterator ri = currentProgram.getReferenceManager().getReferencesTo(f.getEntryPoint());
                while (ri.hasNext()) {
                    Reference r = ri.next(); JsonObject row = new JsonObject();
                    row.addProperty("from", addr(r.getFromAddress())); row.addProperty("type", r.getReferenceType().toString());
                    Function caller = getFunctionContaining(r.getFromAddress());
                    if (caller != null) row.addProperty("containing_function", addr(caller.getEntryPoint())); incoming.add(row);
                }
                root.add("entry_references", incoming);
                DecompileResults result = decompiler.decompileFunction(f, 30, monitor);
                root.addProperty("decompile_completed", result.decompileCompleted());
                root.addProperty("decompile_error", result.getErrorMessage());
                if (result.getDecompiledFunction() != null) root.addProperty("pseudocode", result.getDecompiledFunction().getC());
                Path dest = out.resolve(addr(f.getEntryPoint()) + ".json");
                Files.writeString(dest, new GsonBuilder().setPrettyPrinting().create().toJson(root), StandardCharsets.UTF_8);
                println("FUNCTION_EXPORT " + dest + " completed=" + result.decompileCompleted());
            }
        } finally { decompiler.dispose(); }
    }
}
