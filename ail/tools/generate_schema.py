"""Generate the structural JSON Schema; SSA/types/effects need ail check too."""
import json
from pathlib import Path


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def array(items, **kwargs):
    return {"type": "array", "items": items, **kwargs}


def ref(name):
    return {"$ref": f"#/$defs/{name}"}


def main():
    ident = {"type": "string", "pattern": "^[A-Za-z_][A-Za-z_0-9]*$"}
    typ = {"enum": ["i64", "i1", "ptr"]}
    args = array(ident)
    instructions = []

    def ins(ops, extra):
        instructions.append(obj({"id": ident, "type": typ, "op": {"enum": ops.split()}, **extra}))

    ins("const", {"value": {"oneOf": [{"type": "integer", "minimum": -(1 << 63), "maximum": (1 << 63) - 1}, {"type": "boolean"}]}})
    ins("add sub mul sdiv srem and or xor eq ne slt sle sgt sge", {"args": array(ident, minItems=2, maxItems=2)})
    ins("select", {"cond": ident, "yes": ident, "no": ident})
    ins("call", {"function": ident, "args": array(ident, maxItems=6)})
    ins("addr", {"global": ident})
    ins("write", {"global": ident, "fd": ident})
    ins("syscall", {"number": ident, "args": array(ident, maxItems=6)})
    defs = {
        "param": obj({"id": ident, "type": typ}),
        "edge": obj({"target": ident, "args": args}),
        "instruction": {"oneOf": instructions},
        "term": {"oneOf": [obj({"op": {"const": "ret"}, "value": ident}),
                             obj({"op": {"const": "jump"}, "target": ident, "args": args}),
                             obj({"op": {"const": "branch"}, "cond": ident, "then": ref("edge"), "else": ref("edge")})]},
        "block": obj({"id": ident, "params": array(ref("param")), "instructions": array(ref("instruction")), "term": ref("term")}),
        "function": obj({"id": ident, "params": array(ref("param"), maxItems=6), "return": typ,
                         "effects": array({"enum": ["io", "unsafe"]}, uniqueItems=True), "blocks": array(ref("block"), minItems=1)}),
        "global": obj({"id": ident, "text": {"type": "string"}}),
    }
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "AIL v1 program graph",
              "$defs": defs, **obj({"version": {"const": 1}, "entry": ident, "globals": array(ref("global")), "functions": array(ref("function"), minItems=1)})}
    path = Path(__file__).resolve().parents[1] / "ail.schema.json"
    path.write_text(json.dumps(schema, indent=2) + "\n")


if __name__ == "__main__":
    main()
