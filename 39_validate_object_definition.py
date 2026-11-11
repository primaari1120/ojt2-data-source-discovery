"""Offline regression for object definitions; no SQL Server or SQLite access.

Run: python 39_validate_object_definition.py
"""
from copy import deepcopy
from ojt2_object_definition import object_definition, definition_label


def main():
    table = {'object_type': 'U', 'object_type_desc': 'USER_TABLE',
             'database_name': 'DEMO_Example', 'schema_name': 'ops',
             'object_name': 'Output', 'sql_definition': None}
    cases = [
        ({'sql_type': 'nvarchar', 'max_length': 240}, 'nvarchar(120)'),
        ({'sql_type': 'nchar', 'max_length': 20}, 'nchar(10)'),
        ({'sql_type': 'nvarchar', 'max_length': -1}, 'nvarchar(max)'),
        ({'sql_type': 'varchar', 'max_length': 80}, 'varchar(80)'),
        ({'sql_type': 'varchar', 'max_length': -1}, 'varchar(max)'),
        ({'sql_type': 'char', 'max_length': 12}, 'char(12)'),
        ({'sql_type': 'varbinary', 'max_length': 32}, 'varbinary(32)'),
        ({'sql_type': 'varbinary', 'max_length': -1}, 'varbinary(max)'),
        ({'sql_type': 'binary', 'max_length': 16}, 'binary(16)'),
        ({'sql_type': 'decimal', 'numeric_precision': 19, 'numeric_scale': 4}, 'decimal(19,4)'),
        ({'sql_type': 'numeric', 'numeric_precision': 38, 'numeric_scale': 0}, 'numeric(38,0)'),
        ({'sql_type': 'datetime2', 'numeric_scale': 3}, 'datetime2(3)'),
        ({'sql_type': 'datetimeoffset', 'numeric_scale': 7}, 'datetimeoffset(7)'),
        ({'sql_type': 'time', 'numeric_scale': 0}, 'time(0)'),
        ({'sql_type': 'float', 'numeric_precision': 53}, 'float(53)'),
        ({'sql_type': 'float', 'numeric_precision': 24}, 'float(24)'),
        ({'sql_type': 'int', 'max_length': 4}, 'int NOT NULL'),
        ({'sql_type': 'sysname', 'max_length': 256}, 'sysname NOT NULL'),
        ({'sql_type': 'money', 'numeric_precision': 19, 'numeric_scale': 4}, 'money NOT NULL'),
        ({'sql_type': 'uniqueidentifier'}, 'uniqueidentifier NOT NULL'),
        ({'sql_type': 'custom]Type', 'max_length': 30}, '[custom]]Type] /* type schema not captured */'),
        ({'sql_type': 'nvarchar'}, 'nvarchar /* length unavailable */'),
        ({'sql_type': 'nvarchar', 'max_length': 7}, 'nvarchar /* character length unavailable */'),
        ({'sql_type': 'decimal'}, 'decimal /* precision/scale unavailable */'),
        ({'sql_type': 'numeric', 'numeric_precision': 10, 'numeric_scale': 12}, 'numeric /* precision/scale unavailable */'),
        ({'sql_type': 'datetime2'}, 'datetime2 /* fractional precision unavailable */'),
        ({'sql_type': 'datetime2', 'numeric_scale': 9}, 'datetime2 /* fractional precision unavailable */'),
        ({'sql_type': None}, '/* SQL type unavailable */'),
    ]
    for fields, expected in cases:
        col = {'column_name': 'Example', 'column_id': 1, 'is_nullable': 0, **fields}
        result = object_definition(table, [col])
        assert result.kind == 'column_structure' and expected in result.sql, (fields, result)
        assert 'Partial preview' in result.sql
    columns = [
        {'column_name': 'Name', 'column_id': 3, 'sql_type': 'nvarchar', 'max_length': 80, 'is_nullable': 1},
        {'column_name': 'Key]', 'column_id': 1, 'sql_type': 'int', 'is_nullable': 0, 'is_identity': 1},
        {'column_name': 'Amount', 'column_id': 2, 'sql_type': 'decimal', 'numeric_precision': 18, 'numeric_scale': 2, 'is_nullable': '0'},
    ]
    original = deepcopy((table, columns));result = object_definition(table, columns)
    assert result.sql.index('[Key]]]') < result.sql.index('[Amount]') < result.sql.index('[Name]')
    assert '[Name] nvarchar(40) NULL' in result.sql
    assert '[Amount] decimal(18,2) NOT NULL' in result.sql
    assert 'IDENTITY: seed/increment not captured' in result.sql
    assert 'IDENTITY(1,1)' not in result.sql
    assert (table, columns) == original, 'Snapshot input was mutated'
    assert 'CREATE TABLE [DEMO_Example].[ops].[Output]' in result.sql
    odd = dict(table, database_name='Data]base', schema_name='s]x', object_name='t]x')
    assert '[Data]]base].[s]]x].[t]]x]' in object_definition(odd, columns).sql
    other = dict(table, database_name='DEMO_Other')
    assert object_definition(other, columns).sql != result.sql
    for kind, definition in [
        ('V', 'CREATE VIEW dbo.Example AS SELECT 1 AS Value;\r\n'),
        ('P', 'CREATE PROCEDURE dbo.Example AS SELECT 1;\n'),
        ('FN', 'CREATE FUNCTION dbo.Example() RETURNS int AS BEGIN RETURN 1; END;'),
        ('IF', 'CREATE FUNCTION dbo.Example() RETURNS TABLE AS RETURN SELECT 1 AS Value;'),
        ('TF', 'CREATE FUNCTION dbo.Example() RETURNS @r TABLE(Value int) AS BEGIN RETURN; END;'),
        ('U', '-- actual supplied DDL\nCREATE TABLE dbo.Example(Value int);'),
    ]:
        obj = dict(table, object_type=kind, object_type_desc='', sql_definition=definition)
        assert object_definition(obj, columns).sql == definition, kind
        assert object_definition(obj, columns).kind == 'module'
        assert definition_label(obj, columns) == 'SQL module'
    # A View/Function column list must not masquerade as a reconstructed SELECT.
    for kind in ['V', 'IF', 'TF']:
        obj = dict(table, object_type=kind, object_type_desc='', sql_definition=None)
        preview = object_definition(obj, columns)
        assert preview.kind == 'column_structure'
        assert 'CREATE TABLE' not in preview.sql and 'CREATE VIEW' not in preview.sql
        assert 'does not reconstruct its query' in preview.sql
    for kind in ['U', 'V', 'P', 'FN', 'IF', 'TF']:
        obj = dict(table, object_type=kind, object_type_desc='', sql_definition=None,
                   definition_status='UNAVAILABLE_OR_NO_PERMISSION')
        preview = object_definition(obj, [])
        assert preview.kind == 'unavailable' and not preview.sql
        assert 'UNAVAILABLE_OR_NO_PERMISSION' in preview.note
    missing = object_definition(table, [{'column_name': 'Unknown', 'sql_type': 'int'}])
    assert 'nullability unavailable' in missing.sql
    assert '[Unknown] int NULL' not in missing.sql and '[Unknown] int NOT NULL' not in missing.sql
    assert definition_label(table, columns) == 'Column structure'
    assert object_definition(dict(table, sql_definition='  \n'), columns).kind == 'column_structure'
    print('PASS: 28 type cases; column order, quoting, Unicode byte lengths, nullability, identity,')
    print('      original module preservation, all six object types, partial/absent metadata,')
    print('      qualified identity, and unchanged snapshot inputs. No database accessed.')


if __name__ == '__main__':
    main()
