# Lunite Bytecode Virtual Machine
# -------------------------------

import os
import struct
import importlib
import builtins

from core.lexer import Lexer, Token
from core.parser import Parser
from core.ast import *
from core.constants import *
from runtime.interpreter import Interpreter, SafeModeResourceMonitor
import core.constants as constants

USE_MSGPACK = False
#try:
#    import msgpack
#    USE_MSGPACK = True
#except ImportError:
#    print("[LBVM] [WARN] msgpack is not installed in the current python environment.")
#    print("[LBVM] You can install msgpack with 'pip install msgpack'.")
#    print("[LBVM] [WARN] Using pickle as fallback. This may be less safe.")
#    import pickle
import pickle

# msgpack cannot serialize complex data structs >:(

BYTECODE_MAGIC = b"LUNITE-LBVM\x00"
BYTECODE_VERSION = 1
HEADER_FORMAT = "<12sI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

OP_NOP = 0
OP_LOAD_CONST = 1
OP_LOAD_NAME = 2
OP_STORE_NAME = 3
OP_BINARY_ADD = 4
OP_BINARY_SUB = 5
OP_BINARY_MUL = 6
OP_BINARY_DIV = 7
OP_BINARY_MOD = 8
OP_BIT_AND = 9
OP_BIT_OR = 10
OP_BIT_XOR = 11
OP_LSHIFT = 12
OP_RSHIFT = 13
OP_UNARY_NEG = 14
OP_UNARY_NOT = 15
OP_COMPARE_GT = 16
OP_COMPARE_LT = 17
OP_COMPARE_GE = 18
OP_COMPARE_LE = 19
OP_COMPARE_EQ = 20
OP_COMPARE_NEQ = 21
OP_JUMP = 22
OP_JUMP_IF_FALSE = 23
OP_JUMP_IF_TRUE = 24
OP_CALL_FUNCTION = 25
OP_RETURN_VALUE = 26
OP_POP_TOP = 27
OP_BUILD_LIST = 28
OP_BUILD_DICT = 29
OP_BUILD_SET = 30
OP_BUILD_TUPLE = 31
OP_IMPORT_PY = 32
OP_IMPORT_MODULE = 33
OP_LOAD_ATTR = 34
OP_CALL_METHOD = 35
OP_LOAD_SUBSCRIPT = 36
OP_STORE_SUBSCRIPT = 37
OP_STORE_ATTR = 38
OP_GET_ITER = 39
OP_ITER_NEXT = 40
OP_SWAP = 41
OP_DUP = 42
OP_TYPE_CHECK = 43
OP_TRY_EXCEPT = 44
OP_UNPACK_SEQUENCE = 45
OP_BUILD_SLICE = 46
OP_ASSERT = 47
OP_SETUP_TRY = 48
OP_POP_TRY = 49
OP_BUILD_INSTANCE = 50


class BytecodeProgram:
    def __init__(self, instructions, consts, names, source_file=None):
        self.instructions = instructions
        self.consts = consts
        self.names = names
        self.source_file = source_file


class FunctionObject:
    def __init__(self, name, params, instructions, consts, names, source_file=None):
        self.name = name
        self.params = params
        self.instructions = instructions
        self.consts = consts
        self.names = names
        self.source_file = source_file

    def __repr__(self):
        return f"<FunctionObject {self.name}({', '.join(self.params)})>"


class BytecodeCompiler:
    def __init__(self):
        self.consts = []
        self.names = []
        self.instructions = []
        self.loop_stack = []

    def add_const(self, value):
        for idx, const in enumerate(self.consts):
            if const == value:
                return idx
        self.consts.append(value)
        return len(self.consts) - 1

    def add_name(self, name):
        if name in self.names:
            return self.names.index(name)
        self.names.append(name)
        return len(self.names) - 1

    def emit(self, opcode, arg=None):
        self.instructions.append((opcode, arg))
        return len(self.instructions) - 1

    def patch_jump(self, idx, target):
        opcode, _ = self.instructions[idx]
        self.instructions[idx] = (opcode, target)

    def is_expression(self, node):
        return isinstance(node, (
            Number, String, Char, Boolean, Null, ListLiteral, DictLiteral, SetLiteral, TupleLiteral,
            Identifier, UnaryOp, BinaryOp, TernaryOp, FunctionCall, MethodCall, MemberAccess,
            IndexAccess, SliceAccess, NewInstance, LambdaExpr, TypeCheckOp, UpdateExpr, AwaitExpr
        ))

    def compile(self, node):
        compile_method = getattr(self, f"compile_{type(node).__name__}", None)
        if compile_method is None:
            raise ValueError(f"[LBVM] Unsupported LBVM compile node: {type(node).__name__}")
        compile_method(node)

    def compile_Number(self, node):
        self.emit(OP_LOAD_CONST, self.add_const(node.token.value))

    def compile_String(self, node):
        self.emit(OP_LOAD_CONST, self.add_const(node.token.value))

    def compile_Char(self, node):
        self.emit(OP_LOAD_CONST, self.add_const(node.token.value))

    def compile_Boolean(self, node):
        self.emit(OP_LOAD_CONST, self.add_const(node.value))

    def compile_Null(self, node):
        self.emit(OP_LOAD_CONST, self.add_const(None))

    def compile_Identifier(self, node):
        self.emit(OP_LOAD_NAME, self.add_name(node.token.value))

    def compile_ListLiteral(self, node):
        for element in node.elements:
            self.compile(element)
        self.emit(OP_BUILD_LIST, len(node.elements))

    def compile_DictLiteral(self, node):
        for key, value in node.pairs:
            self.compile(key)
            self.compile(value)
        self.emit(OP_BUILD_DICT, len(node.pairs))

    def compile_TupleLiteral(self, node):
        for element in node.elements:
            self.compile(element)
        self.emit(OP_BUILD_TUPLE, len(node.elements))

    def compile_SetLiteral(self, node):
        for element in node.elements:
            self.compile(element)
        self.emit(OP_BUILD_SET, len(node.elements))

    def compile_UnaryOp(self, node):
        self.compile(node.expr)
        if node.op.type == TOKEN_MINUS:
            self.emit(OP_UNARY_NEG)
        elif node.op.type in (TOKEN_NOT, TOKEN_BIT_NOT):
            self.emit(OP_UNARY_NOT)
        else:
            raise ValueError(f"[LBVM] Unsupported unary operator: {node.op.type}")

    def compile_BinaryOp(self, node):
        op_type = node.op.type
        if op_type == TOKEN_AND:
            self.compile(node.left)
            short_circuit = self.emit(OP_JUMP_IF_FALSE, None)
            self.compile(node.right)
            end_jump = self.emit(OP_JUMP, None)
            self.patch_jump(short_circuit, len(self.instructions))
            self.emit(OP_LOAD_CONST, self.add_const(False))
            self.patch_jump(end_jump, len(self.instructions))
            return

        if op_type == TOKEN_OR:
            self.compile(node.left)
            short_circuit = self.emit(OP_JUMP_IF_TRUE, None)
            self.compile(node.right)
            end_jump = self.emit(OP_JUMP, None)
            self.patch_jump(short_circuit, len(self.instructions))
            self.emit(OP_LOAD_CONST, self.add_const(True))
            self.patch_jump(end_jump, len(self.instructions))
            return

        self.compile(node.left)
        self.compile(node.right)
        if op_type == TOKEN_PLUS:
            self.emit(OP_BINARY_ADD)
        elif op_type == TOKEN_MINUS:
            self.emit(OP_BINARY_SUB)
        elif op_type == TOKEN_MUL:
            self.emit(OP_BINARY_MUL)
        elif op_type == TOKEN_DIV:
            self.emit(OP_BINARY_DIV)
        elif op_type == TOKEN_MOD:
            self.emit(OP_BINARY_MOD)
        elif op_type == TOKEN_BIT_AND:
            self.emit(OP_BIT_AND)
        elif op_type == TOKEN_BIT_OR:
            self.emit(OP_BIT_OR)
        elif op_type == TOKEN_BIT_XOR:
            self.emit(OP_BIT_XOR)
        elif op_type == TOKEN_LSHIFT:
            self.emit(OP_LSHIFT)
        elif op_type == TOKEN_RSHIFT:
            self.emit(OP_RSHIFT)
        elif op_type == TOKEN_GT:
            self.emit(OP_COMPARE_GT)
        elif op_type == TOKEN_LT:
            self.emit(OP_COMPARE_LT)
        elif op_type == TOKEN_GE:
            self.emit(OP_COMPARE_GE)
        elif op_type == TOKEN_LE:
            self.emit(OP_COMPARE_LE)
        elif op_type == TOKEN_EQ:
            self.emit(OP_COMPARE_EQ)
        elif op_type == TOKEN_NEQ:
            self.emit(OP_COMPARE_NEQ)
        else:
            raise ValueError(f"[LBVM] Unsupported binary operator: {op_type}")

    def compile_TernaryOp(self, node):
        self.compile(node.condition)
        false_jump = self.emit(OP_JUMP_IF_FALSE, None)
        self.compile(node.true_expr)
        end_jump = self.emit(OP_JUMP, None)
        self.patch_jump(false_jump, len(self.instructions))
        self.compile(node.false_expr)
        self.patch_jump(end_jump, len(self.instructions))

    def compile_UpdateExpr(self, node):
        if not isinstance(node.target, Identifier):
            raise ValueError("[LBVM] Unsupported update target: only simple identifiers are supported")

        delta = 1 if node.op.type == TOKEN_INC else -1
        self.compile(node.target)
        self.emit(OP_DUP)
        self.emit(OP_LOAD_CONST, self.add_const(delta))
        self.emit(OP_BINARY_ADD if delta == 1 else OP_BINARY_SUB)
        self.emit(OP_DUP)
        self.emit(OP_STORE_NAME, self.add_name(node.target.token.value))

        if node.is_prefix:
            self.emit(OP_SWAP)
            self.emit(OP_POP_TOP)
        else:
            self.emit(OP_POP_TOP)

    def compile_Assign(self, node):
        if isinstance(node.left, Identifier):
            self.compile(node.value)
            self.emit(OP_STORE_NAME, self.add_name(node.left.token.value))
        elif isinstance(node.left, IndexAccess):
            self.compile(node.left.target)
            self.compile(node.left.index)
            self.compile(node.value)
            self.emit(OP_STORE_SUBSCRIPT)
        elif isinstance(node.left, MemberAccess):
            self.compile(node.left.obj)
            self.compile(node.value)
            self.emit(OP_STORE_ATTR, node.left.member_name)
        else:
            raise ValueError("[LBVM] Unsupported assignment target")

    def compile_CompoundAssign(self, node):
        if isinstance(node.left, Identifier):
            self.compile(node.left)
            self.compile(node.value)
            op_type = node.op.type
            if op_type == TOKEN_PLUSEQ:
                self.emit(OP_BINARY_ADD)
            elif op_type == TOKEN_MINUSEQ:
                self.emit(OP_BINARY_SUB)
            elif op_type == TOKEN_MULEQ:
                self.emit(OP_BINARY_MUL)
            elif op_type == TOKEN_DIVEQ:
                self.emit(OP_BINARY_DIV)
            elif op_type == TOKEN_MODEQ:
                self.emit(OP_BINARY_MOD)
            else:
                raise ValueError(f"[LBVM] Unsupported compound assignment: {op_type}")
            self.emit(OP_STORE_NAME, self.add_name(node.left.token.value))
        else:
            raise ValueError("[LBVM] Unsupported compound assignment target")

    def compile_Block(self, node):
        for stmt in node.statements:
            self.compile(stmt)
            if self.is_expression(stmt):
                self.emit(OP_POP_TOP)

    def compile_VarDecl(self, node):
        self.compile(node.value)
        self.emit(OP_STORE_NAME, self.add_name(node.name))

    def compile_IfStatement(self, node):
        self.compile(node.condition)
        false_jump = self.emit(OP_JUMP_IF_FALSE, None)
        self.compile(node.true_block)
        end_jump = self.emit(OP_JUMP, None)
        self.patch_jump(false_jump, len(self.instructions))
        if node.false_block:
            self.compile(node.false_block)
        self.patch_jump(end_jump, len(self.instructions))

    def compile_WhileStatement(self, node):
        loop_start = len(self.instructions)
        self.compile(node.condition)
        false_jump = self.emit(OP_JUMP_IF_FALSE, None)
        self.loop_stack.append({'breaks': [], 'continues': []})
        self.compile(node.body)
        self.emit(OP_JUMP, loop_start)
        end_index = len(self.instructions)
        self.patch_jump(false_jump, end_index)
        loop_data = self.loop_stack.pop()
        for jump_idx in loop_data['breaks']:
            self.patch_jump(jump_idx, end_index)
        for jump_idx in loop_data['continues']:
            self.patch_jump(jump_idx, loop_start)

    def compile_ForStatement(self, node):
        self.compile(node.iterable)
        self.emit(OP_GET_ITER)
        loop_start = len(self.instructions)
        self.emit(OP_ITER_NEXT)
        false_jump = self.emit(OP_JUMP_IF_FALSE, None)
        self.emit(OP_STORE_NAME, self.add_name(node.iterator_name))
        self.loop_stack.append({'breaks': [], 'continues': []})
        self.compile(node.body)
        self.emit(OP_JUMP, loop_start)
        end_index = len(self.instructions)
        self.emit(OP_POP_TOP) # Pop the iterator left on the stack on break/false-jump
        self.patch_jump(false_jump, end_index)
        loop_data = self.loop_stack.pop()
        for jump_idx in loop_data['breaks']:
            self.patch_jump(jump_idx, end_index)
        for jump_idx in loop_data['continues']:
            self.patch_jump(jump_idx, loop_start)

    def compile_BreakStatement(self, node):
        if not self.loop_stack:
            raise ValueError("[LBVM] break outside loop")
        break_jump = self.emit(OP_JUMP, None)
        self.loop_stack[-1]['breaks'].append(break_jump)

    def compile_AdvanceStatement(self, node):
        if not self.loop_stack:
            raise ValueError("[LBVM] advance outside loop")
        continue_jump = self.emit(OP_JUMP, None)
        self.loop_stack[-1]['continues'].append(continue_jump)

    def compile_ReturnStatement(self, node):
        self.compile(node.value)
        self.emit(OP_RETURN_VALUE)

    def compile_FunctionDef(self, node):
        func_compiler = BytecodeCompiler()
        func_compiler.compile(node.body)
        func_compiler.emit(OP_LOAD_CONST, func_compiler.add_const(None))
        func_compiler.emit(OP_RETURN_VALUE)
        params = [p[0] if isinstance(p, tuple) else p for p in node.params]
        func_obj = FunctionObject(node.name, params, func_compiler.instructions, func_compiler.consts, func_compiler.names, node.source_file)
        self.emit(OP_LOAD_CONST, self.add_const(func_obj))
        self.emit(OP_STORE_NAME, self.add_name(node.name))

    def compile_FunctionCall(self, node):
        self.compile(Identifier(Token(TOKEN_ID, node.name, 0, 0)))
        for arg in node.args:
            if isinstance(arg, Assign):
                raise ValueError("[LBVM] Keyword arguments are not currently supported in LBVM.")
            self.compile(arg)
        self.emit(OP_CALL_FUNCTION, len(node.args))

    def compile_MethodCall(self, node):
        self.compile(node.obj)
        for arg in node.args:
            if isinstance(arg, Assign):
                raise ValueError("[LBVM] Keyword arguments are not currently supported in LBVM.")
            self.compile(arg)
        self.emit(OP_CALL_METHOD, (node.method_name, len(node.args)))

    def compile_MemberAccess(self, node):
        self.compile(node.obj)
        self.emit(OP_LOAD_ATTR, node.member_name)

    def compile_IndexAccess(self, node):
        self.compile(node.target)
        self.compile(node.index)
        self.emit(OP_LOAD_SUBSCRIPT)

    def compile_ImportStatement(self, node):
        alias = os.path.splitext(os.path.basename(node.module_name))[0]
        self.emit(OP_IMPORT_MODULE, (node.module_name, alias, node.source_package))

    def compile_ImportPyStatement(self, node):
        self.emit(OP_IMPORT_PY, (node.module_name, node.alias, node.source_package))

    def compile_TypeCheckOp(self, node):
        self.compile(node.expr)
        target_name = node.target_type.token.value if isinstance(node.target_type, Identifier) else str(node.target_type)
        self.emit(OP_LOAD_CONST, self.add_const(target_name))
        self.emit(OP_TYPE_CHECK)

    def compile_AwaitExpr(self, node):
        self.compile(node.expr)

    def compile_LambdaExpr(self, node):
        lambda_compiler = BytecodeCompiler()
        
        if isinstance(node.body, Block):
            lambda_compiler.compile(node.body)
            lambda_compiler.emit(OP_LOAD_CONST, lambda_compiler.add_const(None))
        else:
            lambda_compiler.compile(node.body)
            
        lambda_compiler.emit(OP_RETURN_VALUE)
        
        lambda_func = FunctionObject(
            name="<lambda>",
            params=node.params,
            instructions=lambda_compiler.instructions,
            consts=lambda_compiler.consts,
            names=lambda_compiler.names,
            source_file=""
        )
        
        self.emit(OP_LOAD_CONST, self.add_const(lambda_func))

    def compile_ClassDef(self, node):
        class_compiler = BytecodeCompiler()
        
        for stmt in node.body.statements:
            class_compiler.compile(stmt)
            if class_compiler.is_expression(stmt):
                class_compiler.emit(OP_POP_TOP)
        
        class_compiler.emit(OP_LOAD_CONST, class_compiler.add_const(None))
        class_compiler.emit(OP_RETURN_VALUE)
        
        class_dict = {
            '__lunite__': True,
            'name': node.name,
            'superclass': node.superclass,
            'is_public': node.is_public,
            'instructions': class_compiler.instructions,
            'consts': class_compiler.consts,
            'names': class_compiler.names,
        }
        
        class_const_idx = self.add_const(('__lunite_class__', node.name, class_dict))
        self.emit(OP_LOAD_CONST, class_const_idx)
        self.emit(OP_STORE_NAME, self.add_name(node.name))

    def compile_MatchStatement(self, node):
        self.compile(node.subject)
        end_jumps = []
        for case in node.cases:
            self.emit(OP_DUP)
            self.compile(case.value)
            self.emit(OP_COMPARE_EQ)
            next_case_jump = self.emit(OP_JUMP_IF_FALSE, None)
            
            self.emit(OP_POP_TOP)
            self.compile(case.body)
            end_jumps.append(self.emit(OP_JUMP, None))
            self.patch_jump(next_case_jump, len(self.instructions))
            
        self.emit(OP_POP_TOP)
        if node.default_block:
            self.compile(node.default_block)
            
        for jump in end_jumps:
            self.patch_jump(jump, len(self.instructions))

    def compile_TryCatchStatement(self, node):
        catch_jump = self.emit(OP_SETUP_TRY, None)
        self.compile(node.try_block)
        self.emit(OP_POP_TRY)
        finally_jump = self.emit(OP_JUMP, None)
        
        self.patch_jump(catch_jump, len(self.instructions))
        self.emit(OP_STORE_NAME, self.add_name(node.error_var))
        self.compile(node.catch_block)
        
        self.patch_jump(finally_jump, len(self.instructions))
        if node.finally_block:
            self.compile(node.finally_block)

    def compile_DestructuringDecl(self, node):
        self.compile(node.value)
        self.emit(OP_UNPACK_SEQUENCE, len(node.names))
        for name in reversed(node.names):
            self.emit(OP_STORE_NAME, self.add_name(name))

    def compile_SliceAccess(self, node):
        self.compile(node.target)
        if node.start:
            self.compile(node.start)
        else:
            self.emit(OP_LOAD_CONST, self.add_const(None))
        if node.end:
            self.compile(node.end)
        else:
            self.emit(OP_LOAD_CONST, self.add_const(None))
        self.emit(OP_BUILD_SLICE)

    def compile_AssertStatement(self, node):
        self.compile(node.condition)
        if node.message:
            self.compile(node.message)
        else:
            self.emit(OP_LOAD_CONST, self.add_const("Assertion failed"))
        self.emit(OP_ASSERT)

    def compile_EnumDef(self, node):
        for i, member in enumerate(node.members):
            self.emit(OP_LOAD_CONST, self.add_const(member))
            self.emit(OP_LOAD_CONST, self.add_const(i))
        self.emit(OP_BUILD_DICT, len(node.members))
        self.emit(OP_STORE_NAME, self.add_name(node.name))

    def compile_NewInstance(self, node):
        self.compile(node.class_expr)
        for arg in node.args:
            if isinstance(arg, Assign):
                raise ValueError("[LBVM] Keyword arguments are not currently supported in LBVM.")
            self.compile(arg)
        self.emit(OP_BUILD_INSTANCE, len(node.args))

    def compile_DecoratedFunc(self, node):
        self.compile(node.function)
        self.compile(node.decorator)
        self.emit(OP_LOAD_NAME, self.add_name(node.function.name))
        self.emit(OP_CALL_FUNCTION, 1)
        self.emit(OP_STORE_NAME, self.add_name(node.function.name))
        
    def compile_AsyncFuncDef(self, node):
        self.compile_FunctionDef(node)


class Frame:
    def __init__(self, instructions, consts, names, globals_, locals_, source_file=None):
        self.instructions = instructions
        self.consts = consts
        self.names = names
        self.globals = globals_
        self.locals = locals_
        self.stack = []
        self.ip = 0
        self.source_file = source_file


class BytecodeVM:
    def __init__(self, program, debug=False, safe_mode=False):
        self.program = program
        self.debug = bool(debug)
        self.safe_mode = bool(safe_mode)
        self.safe_violation_reason = None
        self.monitor = None
        self.globals = {}
        self.imported_files = {}
        self.current_file = program.source_file or constants.CURRENT_FILE
        self._build_standard_library()

        if self.safe_mode:
            self.monitor = SafeModeResourceMonitor(self)
            self.monitor.start()

    def _build_standard_library(self):
        interpreter = Interpreter(safe_mode=False, debug=False)
        self.globals.update(interpreter.global_env.values)

    def _stop_monitor(self):
        if self.monitor:
            self.monitor.stop()

    def _check_sandbox(self):
        if self.safe_mode and self.safe_violation_reason:
            raise RuntimeError(self.safe_violation_reason)

    def _load_name(self, frame, name):
        if name in frame.locals:
            return frame.locals[name]
        if name in frame.globals:
            return frame.globals[name]
        if hasattr(builtins, name):
            return getattr(builtins, name)
        raise NameError(f"[LBVM] Undefined name '{name}'")

    def _store_name(self, frame, name, value):
        frame.locals[name] = value

    def _call_function(self, func, args):
        if callable(func) and not isinstance(func, FunctionObject):
            return func(*args)
        if isinstance(func, FunctionObject):
            locals_ = {name: args[i] if i < len(args) else None for i, name in enumerate(func.params)}
            frame = Frame(func.instructions, func.consts, func.names, self.globals, locals_, source_file=func.source_file)
            return self._execute_frame(frame)
        raise RuntimeError(f"[LBVM] '{type(func).__name__}' is not callable")

    def _load_attr(self, obj, attr_name):
        if hasattr(obj, 'methods') and hasattr(obj, 'fields'):
            if attr_name in getattr(obj, 'methods', {}):
                return obj.methods[attr_name]
            if attr_name in getattr(obj, 'fields', {}):
                return obj.fields[attr_name]
        if hasattr(obj, attr_name):
            return getattr(obj, attr_name)
        raise AttributeError(f"[LBVM] Attribute '{attr_name}' not found")

    def _call_method(self, obj, method_name, args):
        if hasattr(obj, 'methods') and method_name in getattr(obj, 'methods', {}):
            method = obj.methods[method_name]
            return method(*args)
        attr = self._load_attr(obj, method_name)
        if callable(attr):
            return attr(*args)
        raise RuntimeError(f"[LBVM] Method '{method_name}' is not callable")

    def _import_python_module(self, module_name, alias, source_package=None):
        if source_package:
            module_name = f"{source_package}.{module_name}"
        module_obj = importlib.import_module(module_name)
        self.globals[alias] = module_obj
        return module_obj

    def _import_luna_module(self, module_name, alias, source_package=None):
        path = module_name
        if source_package:
            path = os.path.join(source_package, module_name)
        if not path.endswith('.luna'):
            path += '.luna'
        path = os.path.normpath(path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"[LBVM] Module not found: {path}")
        if path in self.imported_files:
            self.globals[alias] = self.imported_files[path]
            return self.imported_files[path]

        with open(path, 'r', encoding='utf-8') as f:
            source = f.read()

        interpreter = Interpreter(safe_mode=self.safe_mode, debug=self.debug)
        interpreter.imported_files = self.imported_files
        interpreter.visit(Parser(Lexer(source)).parse())
        module_obj = interpreter.global_env.values.get(alias)
        self.imported_files[path] = module_obj
        self.globals[alias] = module_obj
        return module_obj

    def _type_check(self, value, target_type):
        if target_type == 'int':
            return isinstance(value, int) and not isinstance(value, bool)
        if target_type == 'float':
            return isinstance(value, float)
        if target_type == 'str':
            return isinstance(value, str) and not isinstance(value, bytes)
        if target_type == 'bool':
            return isinstance(value, bool)
        if target_type == 'list':
            return isinstance(value, list)
        if target_type == 'dict':
            return isinstance(value, dict)
        if target_type == 'char':
            return isinstance(value, str) and len(value) == 1
        if target_type == 'byte':
            return isinstance(value, (bytes, bytearray))
        return False

    def _execute_frame(self, frame):
        try_blocks = []

        while frame.ip < len(frame.instructions):
            self._check_sandbox()
            opcode, arg = frame.instructions[frame.ip]
            frame.ip += 1

            if self.debug:
                print(f"[LBVM] [DEBUG] {frame.ip - 1}: {opcode} {arg}")
            
            try:
                if opcode == OP_LOAD_CONST:
                    frame.stack.append(frame.consts[arg])
                elif opcode == OP_LOAD_NAME:
                    frame.stack.append(self._load_name(frame, frame.names[arg]))
                elif opcode == OP_STORE_NAME:
                    self._store_name(frame, frame.names[arg], frame.stack.pop())
                elif opcode == OP_POP_TOP:
                    frame.stack.pop()
                elif opcode == OP_BINARY_ADD:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left + right)
                elif opcode == OP_BINARY_SUB:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left - right)
                elif opcode == OP_BINARY_MUL:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left * right)
                elif opcode == OP_BINARY_DIV:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left / right)
                elif opcode == OP_BINARY_MOD:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left % right)
                elif opcode == OP_BIT_AND:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left & right)
                elif opcode == OP_BIT_OR:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left | right)
                elif opcode == OP_BIT_XOR:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left ^ right)
                elif opcode == OP_LSHIFT:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left << right)
                elif opcode == OP_RSHIFT:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left >> right)
                elif opcode == OP_SWAP:
                    a = frame.stack.pop(); b = frame.stack.pop(); frame.stack.append(a); frame.stack.append(b)
                elif opcode == OP_DUP:
                    frame.stack.append(frame.stack[-1])
                elif opcode == OP_UNARY_NEG:
                    frame.stack.append(-frame.stack.pop())
                elif opcode == OP_UNARY_NOT:
                    frame.stack.append(not frame.stack.pop())
                elif opcode == OP_COMPARE_GT:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left > right)
                elif opcode == OP_COMPARE_LT:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left < right)
                elif opcode == OP_COMPARE_GE:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left >= right)
                elif opcode == OP_COMPARE_LE:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left <= right)
                elif opcode == OP_COMPARE_EQ:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left == right)
                elif opcode == OP_COMPARE_NEQ:
                    right = frame.stack.pop(); left = frame.stack.pop(); frame.stack.append(left != right)
                elif opcode == OP_JUMP:
                    frame.ip = arg
                elif opcode == OP_JUMP_IF_FALSE:
                    if not frame.stack.pop():
                        frame.ip = arg
                elif opcode == OP_JUMP_IF_TRUE:
                    if frame.stack.pop():
                        frame.ip = arg
                elif opcode == OP_CALL_FUNCTION:
                    args = [frame.stack.pop() for _ in range(arg)][::-1]
                    func = frame.stack.pop()
                    frame.stack.append(self._call_function(func, args))
                elif opcode == OP_RETURN_VALUE:
                    return frame.stack.pop() if frame.stack else None
                elif opcode == OP_BUILD_LIST:
                    frame.stack.append([frame.stack.pop() for _ in range(arg)][::-1])
                elif opcode == OP_BUILD_DICT:
                    mapping = {}
                    for _ in range(arg):
                        value = frame.stack.pop(); key = frame.stack.pop()
                        mapping[key] = value
                    frame.stack.append(mapping)
                elif opcode == OP_BUILD_TUPLE:
                    frame.stack.append(tuple(frame.stack.pop() for _ in range(arg))[::-1])
                elif opcode == OP_BUILD_SET:
                    frame.stack.append({frame.stack.pop() for _ in range(arg)})
                elif opcode == OP_IMPORT_PY:
                    module_name, alias, source_package = arg
                    self._import_python_module(module_name, alias, source_package)
                elif opcode == OP_IMPORT_MODULE:
                    module_name, alias, source_package = arg
                    self._import_luna_module(module_name, alias, source_package)
                elif opcode == OP_LOAD_ATTR:
                    obj = frame.stack.pop()
                    frame.stack.append(self._load_attr(obj, arg))
                elif opcode == OP_CALL_METHOD:
                    args = [frame.stack.pop() for _ in range(arg[1])][::-1]
                    obj = frame.stack.pop()
                    frame.stack.append(self._call_method(obj, arg[0], args))
                elif opcode == OP_LOAD_SUBSCRIPT:
                    index = frame.stack.pop(); target = frame.stack.pop(); frame.stack.append(target[index])
                elif opcode == OP_STORE_SUBSCRIPT:
                    value = frame.stack.pop(); index = frame.stack.pop(); target = frame.stack.pop(); target[index] = value
                elif opcode == OP_STORE_ATTR:
                    value = frame.stack.pop(); obj = frame.stack.pop(); setattr(obj, arg, value)
                elif opcode == OP_GET_ITER:
                    frame.stack.append(iter(frame.stack.pop()))
                elif opcode == OP_ITER_NEXT:
                    iterator = frame.stack[-1]
                    try:
                        frame.stack.append(next(iterator))
                        frame.stack.append(True)
                    except StopIteration:
                        frame.stack.append(False)
                elif opcode == OP_TYPE_CHECK:
                    target_type = frame.stack.pop(); value = frame.stack.pop(); frame.stack.append(self._type_check(value, target_type))
                elif opcode == OP_UNPACK_SEQUENCE:
                    seq = frame.stack.pop()
                    if len(seq) < arg:
                        raise ValueError(f"[LBVM] Not enough values to unpack (expected {arg}, got {len(seq)})")
                    for item in reversed(list(seq)[:arg]):
                        frame.stack.append(item)
                elif opcode == OP_BUILD_SLICE:
                    end = frame.stack.pop()
                    start = frame.stack.pop()
                    target = frame.stack.pop()
                    frame.stack.append(target[start:end])
                elif opcode == OP_ASSERT:
                    msg = frame.stack.pop()
                    cond = frame.stack.pop()
                    if not cond:
                        raise RuntimeError(f"[LBVM] Assertion failed: {msg}")
                elif opcode == OP_BUILD_INSTANCE:
                    args = [frame.stack.pop() for _ in range(arg)][::-1]
                    cls = frame.stack.pop()
                    if isinstance(cls, tuple) and cls[0] == '__lunite_class__':
                        instance = type(cls[1], (), {})()
                        instance.__dict__.update(cls[2])
                        frame.stack.append(instance)
                    else:
                        frame.stack.append(cls(*args))
                elif opcode == OP_SETUP_TRY:
                    try_blocks.append(arg)
                elif opcode == OP_POP_TRY:
                    if try_blocks: try_blocks.pop()
                else:
                    raise RuntimeError(f"[LBVM] Unknown opcode: {opcode}")
            except Exception as e:
                if try_blocks:
                    catch_ip = try_blocks.pop()
                    frame.ip = catch_ip
                    frame.stack.append(getattr(e, "message_only", str(e)))
                else:
                    raise e
        return None

    def run(self):
        try:
            frame = Frame(self.program.instructions, self.program.consts, self.program.names, self.globals, {}, source_file=self.program.source_file)
            return self._execute_frame(frame)
        finally:
            self._stop_monitor()


def program_to_dict(program: BytecodeProgram):
    return {
        "instructions": program.instructions,
        "consts": program.consts,
        "names": program.names,
        "source_file": program.source_file,
    }

def dict_to_program(d):
    return BytecodeProgram(
        d["instructions"],
        d["consts"],
        d["names"],
        d.get("source_file"),
    )


def compile_ast_to_bytecode(source, source_file=None):
    lexer = Lexer(source)
    tokens = list(lexer)
    parser = Parser(tokens)
    ast = parser.parse()
    compiler = BytecodeCompiler()
    compiler.compile(ast)
    return BytecodeProgram(compiler.instructions, compiler.consts, compiler.names, source_file)


def save_bytecode(path, source, source_file=None):
    program = compile_ast_to_bytecode(source, source_file)
    data = program_to_dict(program)
    if USE_MSGPACK:
        payload = msgpack.packb(data, use_bin_type=True)
    else:
        payload = pickle.dumps(data)
    with open(path, "wb") as f:
        f.write(struct.pack(HEADER_FORMAT, BYTECODE_MAGIC, BYTECODE_VERSION))
        f.write(payload)
    return path


def load_bytecode(path):
    with open(path, "rb") as f:
        header = f.read(HEADER_SIZE)
        if len(header) != HEADER_SIZE:
            raise ValueError("[LBVM] Invalid Lunite bytecode file: wrong header size")
        magic, version = struct.unpack(HEADER_FORMAT, header)
        if magic != BYTECODE_MAGIC:
            raise ValueError("[LBVM] Invalid Lunite bytecode file: wrong bytecode magic")
        if version != BYTECODE_VERSION:
            raise ValueError(f"[LBVM] Unsupported Lunite bytecode version, expected '{BYTECODE_VERSION}', got '{version}'")
        payload = f.read()
        if USE_MSGPACK:
            data = msgpack.unpackb(payload, raw=False)
        else:
            data = pickle.loads(payload)

    if not isinstance(data, dict) or "instructions" not in data:
        raise ValueError("[LBVM] Invalid bytecode payload")
    program = dict_to_program(data)
    return program, program.source_file


def detect_python_imports(program):
    modules = set()
    
    def scan(instructions, consts):
        for opcode, arg in instructions:
            if opcode == OP_IMPORT_PY and arg:
                mod_name = arg[0]
                if mod_name:
                    root_mod = mod_name.split('.')[0]
                    modules.add(root_mod)
                    
        for const in consts:
            if isinstance(const, FunctionObject):
                scan(const.instructions, const.consts)
            elif isinstance(const, tuple) and len(const) == 3 and const[0] == '__lunite_class__':
                class_dict = const[2]
                if isinstance(class_dict, dict):
                    scan(class_dict.get('instructions', []), class_dict.get('consts', []))
                    
    scan(program.instructions, program.consts)
    return list(modules)


def run_bytecode(path, debug=False, sandbox=False):
    program, source_file = load_bytecode(path)
    old_file = constants.CURRENT_FILE
    if source_file:
        constants.CURRENT_FILE = source_file

    vm = BytecodeVM(program, debug=debug, safe_mode=sandbox)
    if debug:
        print(f"[LBVM] [DEBUG] Running bytecode: {path}")
        print(f"[LBVM] [DEBUG] Source file: {source_file}")

    vm.run()
    constants.CURRENT_FILE = old_file


if __name__ == "__main__":
    raise RuntimeError("This module is not intended to be executed directly.")
