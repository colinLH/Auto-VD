"""Reviewed byte-layout codec for protocol plugins; no model-inferred offsets.

Fields are in wire order. Supports integers, enums, opaque bytes, explicit
length prefixes/references, and conditional fields selected by an earlier value.
Bit-packed flags can be represented as one bitmap container. More complex
protocols may supply a different codec with the same deserialize/layout API.
"""
from dataclasses import dataclass
from types import SimpleNamespace


@dataclass(frozen=True)
class DecodedPayload:
    wire: bytes
    def serialize(self):
        return self.wire


class WireSchema:
    def __init__(self, fields, *, byteorder='big', max_payload=128):
        self.definitions = tuple(dict(f) for f in fields)
        self.byteorder, self.max_payload = byteorder, max_payload
        if byteorder not in ('big', 'little') or max_payload < 1:
            raise ValueError('Invalid schema encoding/bound')
        names = set()
        descriptors = []
        for f in self.definitions:
            name = f.get('name')
            if not name or name in names or f.get('kind', 'bytes') not in ('int','uint','enum','bitmap','bool','bytes','string'):
                raise ValueError('Unique field names and explicit supported kinds required')
            refs = set(f.get('present_if', {})) | ({f['length_from']} if f.get('length_from') else set())
            if refs - names:
                raise ValueError('Layout dependencies must reference earlier fields')
            if type(f.get('size', 0)) is not int or f.get('size', 0) < 0:
                raise ValueError('Invalid field size')
            if type(f.get('length_prefix', 0)) is not int or not 0 <= f.get('length_prefix', 0) <= 4:
                raise ValueError('Invalid length prefix')
            if not (f.get('size') or f.get('length_prefix') or f.get('length_from')):
                raise ValueError('Field requires a size or explicit length encoding')
            kind = bytes if f.get('kind','bytes') in ('bytes','string') else int
            if f.get('kind') == 'enum':
                kind = type('WireEnum', (int,), {'__members__': {str(v):v for v in f.get('values',())}})
            descriptors.append(SimpleNamespace(name=name, type=kind))
            names.add(name)
        self.fields = tuple(descriptors)

    def decode_layout(self, payload):
        if len(payload) > self.max_payload:
            raise ValueError('Payload exceeds declared protocol bound')
        offset, values, fields = 0, {}, []
        for f, descriptor in zip(self.definitions, self.fields):
            if any(values.get(key) not in (allowed if isinstance(allowed, list) else [allowed])
                   for key, allowed in f.get('present_if', {}).items()):
                continue
            order = f.get('byteorder', self.byteorder)
            prefix = f.get('length_prefix',0)
            if order not in ('big','little'):
                raise ValueError('Invalid field byteorder')
            if prefix:
                if offset + prefix > len(payload):
                    raise ValueError('Missing length prefix')
                size = prefix + int.from_bytes(payload[offset:offset+prefix],order)
            elif f.get('length_from'):
                length = values[f['length_from']]
                if type(length) is not int or length < 0:
                    raise ValueError('Invalid dependent length')
                size = length
            else:
                size = f['size']
            if offset + size > len(payload):
                raise ValueError('Truncated field')
            wire = payload[offset:offset+size]
            numeric = f.get('kind','bytes') not in ('bytes','string')
            value = int.from_bytes(wire,order,signed=f.get('signed',f.get('kind')=='int')) if numeric else wire[prefix:]
            if f.get('kind') == 'enum' and value not in f.get('values',()):
                raise ValueError('Undeclared enumeration value')
            if f.get('kind') == 'bool' and value not in (0,1):
                raise ValueError('Invalid Boolean encoding')
            fields.append(dict(name=f['name'],offset=offset,size=size,value=value,wire=wire,
                               type=descriptor.type,byteorder=order,length_prefix=prefix))
            values[f['name']] = value
            offset += size
        if offset != len(payload):
            raise ValueError('Trailing bytes in canonical seed')
        return fields

    def deserialize(self, payload):
        self.decode_layout(payload)
        return DecodedPayload(payload), b''
