// Export analyzed incoming references without mutating the program.
// @category Burnout3
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import com.google.gson.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;

public class ExportAddressRefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        JsonObject root = new JsonObject();
        root.addProperty("sha256", currentProgram.getExecutableSHA256());
        root.addProperty("language", currentProgram.getLanguageID().toString());
        root.addProperty("scope", "Ghidra analyzed exact-address references; unresolved computed references may be absent");
        JsonArray targets = new JsonArray();
        for (int i = 1; i < args.length; i++) {
            Address target = toAddr(args[i]); JsonObject item = new JsonObject();
            item.addProperty("address", target.toString()); JsonArray refs = new JsonArray();
            ReferenceIterator iterator = currentProgram.getReferenceManager().getReferencesTo(target);
            while (iterator.hasNext()) {
                Reference ref = iterator.next(); JsonObject row = new JsonObject();
                row.addProperty("from", ref.getFromAddress().toString()); row.addProperty("type", ref.getReferenceType().toString());
                Function f = getFunctionContaining(ref.getFromAddress());
                if (f != null) row.addProperty("function_entry", f.getEntryPoint().toString());
                Instruction insn = getInstructionAt(ref.getFromAddress());
                if (insn != null) row.addProperty("instruction", insn.toString()); refs.add(row);
            }
            item.add("incoming_references", refs); targets.add(item);
        }
        root.add("targets", targets);
        Path dest = Paths.get(args[0]); Files.createDirectories(dest.getParent());
        Files.writeString(dest, new GsonBuilder().setPrettyPrinting().create().toJson(root), StandardCharsets.UTF_8);
        println("REFERENCE_EXPORT " + dest);
    }
}
