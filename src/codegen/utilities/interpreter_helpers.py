"""This contains the helper methods used in interpreter generation."""
import re
from copy import deepcopy

from codegen.functions.function import Function
from codegen.utilities.helpers import camel_to_snake_case

# This custom regex list doesn't split the string before the number.
INTERPRETER_CAMEL_TO_SNAKE_CASE_REGEXES = [
    re.compile("([^_\n])([A-Z][a-z]+)"),
    re.compile("([a-z])([A-Z])"),
    re.compile("([0-9])([^_0-9])"),
]

INTERPRETER_IGNORED_FUNCTIONS = [
    "GetExtendedErrorInfo",
    "GetArmStartTrigTimestampVal",
    "GetFirstSampTimestampVal",
    "GetRefTrigTimestampVal",
    "GetStartTrigTimestampVal",
    "GetTimingAttributeExTimestamp",
    "GetTimingAttributeTimestamp",
    "GetTrigAttributeTimestamp",
    "SetTimingAttributeExTimestamp",
    "SetTimingAttributeTimestamp",
    "SetTrigAttributeTimestamp",
    "GetArmStartTrigTrigWhen",
    "GetFirstSampClkWhen",
    "GetStartTrigTrigWhen",
    "GetSyncPulseTimeWhen",
    "SetArmStartTrigTrigWhen",
    "SetFirstSampClkWhen",
    "SetStartTrigTrigWhen",
    "SetSyncPulseTimeWhen",
]

LIBRARY_INTERPRETER_IGNORED_FUNCTIONS = [
    "RegisterSignalEvent",
    "RegisterEveryNSamplesEvent",
    "RegisterDoneEvent",
]


def get_interpreter_functions(metadata, is_base_interpreter=False):
    """Converts the scrapigen metadata into a list of functions."""
    all_functions = deepcopy(metadata["functions"])
    functions_metadata = []
    for function_name, function_data in all_functions.items():
        if not is_base_interpreter:
            if (
                not is_python_codegen_method(function_data)
                or function_name in LIBRARY_INTERPRETER_IGNORED_FUNCTIONS
            ):
                continue
        if function_name in INTERPRETER_IGNORED_FUNCTIONS:
            continue
        function_data["c_function_name"] = function_name
        function_name = camel_to_snake_case(function_name, INTERPRETER_CAMEL_TO_SNAKE_CASE_REGEXES)
        function_name = function_name.replace("_u_int", "_uint")
        skippable_params = get_skippable_params_for_interpreter_func(function_data)
        function_data["parameters"] = (
            p for p in function_data["parameters"] if p["name"] not in skippable_params
        )
        functions_metadata.append(
            Function(
                function_name,
                function_data,
            )
        )

    return sorted(functions_metadata, key=lambda x: x._function_name)


def generate_interpreter_function_call_args(function_metadata):
    """Gets function call arguments."""
    function_call_args = []
    for param in function_metadata.base_parameters:
        if param.direction == "in":
            function_call_args.append(param.parameter_name)
            if param.has_explicit_buffer_size:
                function_call_args.append(f"len({param.parameter_name})")
        else:
            if param.has_explicit_buffer_size:
                if param.size.mechanism == "ivi-dance":
                    function_call_args.append(param.parameter_name)
                    function_call_args.append("temp_size")
                elif (
                    param.size.mechanism == "passed-in"
                    or param.size.mechanism == "passed-in-by-ptr"
                    or param.size.mechanism == "custom-code"
                ):
                    function_call_args.append(f"ctypes.byref({param.parameter_name})")
            else:
                function_call_args.append(f"ctypes.byref({param.parameter_name})")

    return function_call_args


def get_interpreter_parameter_signature(is_python_factory, params):
    """Gets parameter signature for function defintion."""
    params_with_defaults = []
    if not is_python_factory:
        params_with_defaults.append("self")
    for param in params:
        if param.type:
            params_with_defaults.append(param.parameter_name)

    return ", ".join(params_with_defaults)


def get_instantiation_lines_for_output_params(output_parameters):
    """Gets the lines of code for instantiation of output parameters."""
    instantiation_lines = []
    for param in output_parameters:
        if param.has_explicit_buffer_size:
            if (
                param.size.mechanism == "passed-in" or param.size.mechanism == "passed-in-by-ptr"
            ) and param.is_list:
                instantiation_lines.append(
                    f"{param.parameter_name} = numpy.zeros({param.size.value}, dtype=numpy.{param.ctypes_data_type})"
                )
        else:
            instantiation_lines.append(f"{param.parameter_name} = {param.ctypes_data_type}()")
    return instantiation_lines


def get_interpreter_params(func):
    """Gets interpreter parameters for the function."""
    return (p for p in func.base_parameters if p.direction == "in")


def get_skippable_params_for_interpreter_func(func):
    """Gets parameter names that needs to be skipped for the function."""
    skippable_params = []
    ignored_mechanisms = ["ivi-dance"]
    for param in func["parameters"]:
        size = param.get("size", {})
        if size.get("mechanism") in ignored_mechanisms:
            skippable_params.append(size.get("value"))
        if is_skippable_param(param):
            skippable_params.append(param["name"])
    return skippable_params


def is_skippable_param(param: dict) -> bool:
    """Checks whether the parameter can be skipped or not while generating interpreter."""
    ignored_params = ["size", "reserved"]
    if (not param.get("include_in_proto", True) and (param["name"] in ignored_params)) or param.get(
        "proto_only"
    ):
        return True
    return False


def is_python_codegen_method(func: dict) -> bool:
    """Returns True if the method is a python codegen method."""
    if "python_codegen_method" in func:
        return func["python_codegen_method"] != "no"
    return True


def get_output_param_with_ivi_dance_mechanism(output_parameters):
    """Gets the output parameters with explicit buffer size."""
    explicit_output_params = [p for p in output_parameters if p.has_explicit_buffer_size]
    params_with_ivi_dance_mechanism = [
        p for p in explicit_output_params if p.size.mechanism == "ivi-dance"
    ]
    if len(params_with_ivi_dance_mechanism) > 1:
        raise NotImplementedError(
            "There is more than one output parameter with an explicit "
            "buffer size that follows ivi dance mechanism."
            "This cannot be handled by this template because it "
            'calls the C function once with "buffer_size = 0" to get the '
            "buffer size from the returned integer, which is normally an "
            "error code.\n\n"
            "Output parameters with explicit buffer sizes: {}".format(
                params_with_ivi_dance_mechanism
            )
        )

    if len(params_with_ivi_dance_mechanism) == 1:
        return params_with_ivi_dance_mechanism[0]
    return None


def has_parameter_with_ivi_dance_size_mechanism(func):
    """Returns true if the function has a parameter with ivi dance size mechanism."""
    parameter_with_size_buffer = get_output_param_with_ivi_dance_mechanism(func.output_parameters)
    return parameter_with_size_buffer is not None


def get_output_params(func):
    """Gets input parameters for the function."""
    return (p for p in func.base_parameters if p.direction == "out")


def get_output_parameter_names(func):
    """Gets the names of the output parameters of the given function."""
    output_parameters = get_output_params(func)
    return [p.parameter_name for p in output_parameters]


def get_c_function_call_template(func):
    """Gets the template to use for generating the logic of calling the c functions."""
    if has_parameter_with_ivi_dance_size_mechanism(func):
        return "/double_c_function_call.py.mako"
    return "/default_c_function_call.py.mako"