"""Display SQL modules or annotated column structure from an existing snapshot.

No database access or SQL execution. Reconstructed structure is intentionally
partial: the current catalog does not capture original table DDL, constraints,
defaults, computed expressions, collation, or identity seed/increment.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class DefinitionPreview:
    kind: str
    sql: str
    note: str


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            pass
    return None


def _flag(value: Any) -> bool | None:
    if value in (True, 1, '1'):
        return True
    if value in (False, 0, '0'):
        return False
    return None


def quote_identifier(value: Any) -> str:
    return '[' + str(value).replace(']', ']]') + ']'


def _qualified_name(obj: Mapping[str, Any]) -> str:
    parts = [obj.get(k) for k in ('database_name', 'schema_name', 'object_name')]
    return '.'.join(quote_identifier(p) for p in parts if p is not None and str(p)) or '[unknown object]'


def _is_table(obj: Mapping[str, Any]) -> bool:
    return (str(obj.get('object_type', '')).strip().upper() in {'U', 'TABLE', 'USER_TABLE'}
            or str(obj.get('object_type_desc', '')).strip().upper() in {'TABLE', 'USER_TABLE'})


def _sql_type(column: Mapping[str, Any]) -> str:
    name = str(column.get('sql_type') or '').strip()
    typ = name.lower()
    if not name:
        return '/* SQL type unavailable */'
    if typ in {'char', 'varchar', 'nchar', 'nvarchar', 'binary', 'varbinary'}:
        length = _integer(column.get('max_length'))
        if length == -1 and typ in {'varchar', 'nvarchar', 'varbinary'}:
            return typ + '(max)'
        if length is not None and length > 0:
            # sys.columns stores Unicode length in bytes, not characters.
            if typ in {'nchar', 'nvarchar'}:
                if length % 2:
                    return typ + ' /* character length unavailable */'
                length //= 2
            return f'{typ}({length})'
        return typ + ' /* length unavailable */'
    if typ in {'decimal', 'numeric'}:
        precision = _integer(column.get('numeric_precision'))
        scale = _integer(column.get('numeric_scale'))
        if precision is not None and scale is not None and 1 <= precision <= 38 and 0 <= scale <= precision:
            return f'{typ}({precision},{scale})'
        return typ + ' /* precision/scale unavailable */'
    if typ in {'time', 'datetime2', 'datetimeoffset'}:
        scale = _integer(column.get('numeric_scale'))
        if scale is not None and 0 <= scale <= 7:
            return f'{typ}({scale})'
        return typ + ' /* fractional precision unavailable */'
    if typ == 'float':
        precision = _integer(column.get('numeric_precision'))
        if precision is not None and 1 <= precision <= 53:
            return f'float({precision})'
        return 'float /* precision unavailable */'
    if typ in {'bigint', 'bit', 'date', 'datetime', 'image', 'int', 'money',
               'ntext', 'real', 'rowversion', 'smalldatetime', 'smallint',
               'smallmoney', 'sql_variant', 'sysname', 'text', 'timestamp',
               'tinyint', 'uniqueidentifier', 'xml', 'geography', 'geometry',
               'hierarchyid'}:
        return typ
    # The snapshot stores a type name but not its schema; do not invent dbo.
    return quote_identifier(name) + ' /* type schema not captured */'


def _column_line(column: Mapping[str, Any]) -> str:
    name = quote_identifier(column.get('column_name') or 'unknown column')
    value = name + ' ' + _sql_type(column)
    nullable = _flag(column.get('is_nullable'))
    value += (' NULL' if nullable else ' NOT NULL') if nullable is not None else ' /* nullability unavailable */'
    if _flag(column.get('is_identity')):
        # Never silently assume IDENTITY(1,1); only the flag is captured.
        value += ' /* IDENTITY: seed/increment not captured */'
    return value


def object_definition(obj: Mapping[str, Any], columns: Sequence[Mapping[str, Any]] = ()) -> DefinitionPreview:
    """Prefer the actual stored module; otherwise show available column metadata.

    A View/Function with no module can expose its columns, but this does not
    reconstruct its SELECT or business logic. No SP definition is inferred from
    a table, and no empty CREATE statement is fabricated when columns are absent.
    """
    module = obj.get('sql_definition')
    if isinstance(module, str) and module.strip():
        return DefinitionPreview('module', module, 'SQL definition dari metadata snapshot.')
    if columns:
        ordered = sorted(enumerate(columns), key=lambda pair: (
            _integer(pair[1].get('column_id')) if _integer(pair[1].get('column_id')) is not None else pair[0] + 1,
            pair[0],
        ))
        body = ',\n'.join('    ' + _column_line(col) for _, col in ordered)
        name = _qualified_name(obj)
        if _is_table(obj):
            sql = ('-- Reconstructed column structure from metadata snapshot.\n'
                   '-- Partial preview, not the original/full CREATE TABLE DDL.\n'
                   f'CREATE TABLE {name} (\n{body}\n);')
            note = ('Struktur kolom dari snapshot; bukan DDL asli/lengkap. Default, computed expression, '
                    'constraint, index, collation, serta seed/increment IDENTITY belum dicakup. '
                    'SP pembentuk/pengisi ditelusuri terpisah melalui lineage GENERATED_BY.')
        else:
            sql = (f'-- Column structure: {name}\n'
                   '-- SQL module unavailable; this does not reconstruct its query or logic.\n'
                   f'(\n{body}\n)')
            note = ('SQL module definition belum tersedia pada snapshot. Berikut struktur kolom yang tersedia; '
                    'query dan logika objek tidak direkonstruksi.')
        return DefinitionPreview('column_structure', sql, note)
    status = str(obj.get('definition_status') or 'Tidak tercatat pada snapshot')
    return DefinitionPreview('unavailable', '',
        f'Definisi SQL dan struktur kolom belum tersedia pada snapshot. Status: {status}. '
        'Periksa kelengkapan snapshot, izin VIEW DEFINITION, atau kemungkinan enkripsi modul.')


def definition_label(obj: Mapping[str, Any], columns: Sequence[Mapping[str, Any]] = ()) -> str:
    """Availability label without rendering or constructing the SQL preview."""
    if isinstance(obj.get('sql_definition'), str) and obj['sql_definition'].strip():
        return 'SQL module'
    if columns:
        return 'Column structure'
    return str(obj.get('definition_status') or 'Unavailable')


def render_object_definition(obj: Mapping[str, Any], columns: Sequence[Mapping[str, Any]] = ()) -> None:
    import streamlit as st
    preview = object_definition(obj, columns)
    if preview.sql:
        st.caption(preview.note)
        st.code(preview.sql, language='sql', line_numbers=True)
    else:
        st.info(preview.note)
