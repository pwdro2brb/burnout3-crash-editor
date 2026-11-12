// Export original program observations. No executable bytes are changed.
// @category Burnout3
import ghidra.app.util.headless.HeadlessScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.*;
import com.google.gson.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public class CrashTriage extends HeadlessScript {
    private String addr(Address a) { return a == null ? null : a.toString(); }
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Path output = Paths.get(args[0]);
        Files.createDirectories(output);
        JsonObject root = new JsonObject();
        root.addProperty("program", currentProgram.getName());
        root.addProperty("sha256", currentProgram.getExecutableSHA256());
        root.addProperty("language", currentProgram.getLanguageID().toString());
        root.addProperty("compiler_spec", currentProgram.getCompilerSpec().getCompilerSpecID().toString());
        root.addProperty("current_headless_analysis_timed_out", analysisTimeoutOccurred());
        root.addProperty("function_count", currentProgram.getFunctionManager().getFunctionCount());
        JsonArray blocks = new JsonArray();
        for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
            JsonObject b = new JsonObject();
            b.addProperty("name", block.getName()); b.addProperty("start", addr(block.getStart()));
            b.addProperty("end_inclusive", addr(block.getEnd())); b.addProperty("bytes", block.getSize());
            b.addProperty("initialized", block.isInitialized()); b.addProperty("read", block.isRead());
            b.addProperty("write", block.isWrite()); b.addProperty("execute", block.isExecute()); blocks.add(b);
        }
        root.add("blocks", blocks);
        JsonArray candidates = new JsonArray();
        for (String line : Files.readAllLines(Paths.get(args[1]), StandardCharsets.UTF_8)) {
            monitor.checkCancelled();
            String[] fields = line.split("\t", 3);
            Address target = toAddr(fields[0]);
            JsonObject item = new JsonObject();
            item.addProperty("address", addr(target)); item.addProperty("file_offset_hex", fields[1]);
            item.addProperty("text", fields[2]);
            JsonArray references = new JsonArray();
            ReferenceIterator iterator = currentProgram.getReferenceManager().getReferencesTo(target);
            while (iterator.hasNext()) {
                Reference ref = iterator.next();
                JsonObject r = new JsonObject();
                r.addProperty("from", addr(ref.getFromAddress()));
                r.addProperty("type", ref.getReferenceType().toString());
                Function f = getFunctionContaining(ref.getFromAddress());
                if (f != null) {r.addProperty("function", f.getName()); r.addProperty("entry", addr(f.getEntryPoint()));}
                references.add(r);
            }
            item.add("incoming_references", references); candidates.add(item);
        }
        root.add("candidate_strings", candidates);
        JsonArray funcs = new JsonArray();
        FunctionIterator fi = currentProgram.getFunctionManager().getFunctions(true);
        while (fi.hasNext()) {
            Function f = fi.next(); JsonObject item = new JsonObject();
            item.addProperty("entry", addr(f.getEntryPoint())); item.addProperty("name", f.getName());
            item.addProperty("body_bytes", f.getBody().getNumAddresses()); item.addProperty("thunk", f.isThunk());
            funcs.add(item);
        }
        root.add("functions", funcs);
        Path dest = output.resolve("ghidra_triage.json");
        Files.writeString(dest, new GsonBuilder().setPrettyPrinting().create().toJson(root), StandardCharsets.UTF_8);
        println("TRIAGE_EXPORT " + dest + " language=" + currentProgram.getLanguageID() + " functions=" + funcs.size());
    }
}
