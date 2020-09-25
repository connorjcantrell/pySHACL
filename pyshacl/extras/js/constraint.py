import typing
from typing import List, Dict, Tuple
from rdflib import Literal
from pyshacl.constraints import ConstraintComponent
from pyshacl.constraints.constraint_component import CustomConstraintComponent
from pyshacl.consts import SH, SH_message, SH_js, SH_jsLibrary, SH_jsFunctionName, SH_ConstraintComponent
from pyshacl.errors import ConstraintLoadError, ValidationFailure, ReportableRuntimeError
from pyshacl.pytypes import GraphLike
from .context import SHACLJSContext
if typing.TYPE_CHECKING:
    from pyshacl.shapes_graph import ShapesGraph
    from pyshacl.shape import Shape


SH_jsLibraryURL = SH.term('jsLibraryURL')
SH_JSConstraint = SH.term('JSConstraint')
SH_JSConstraintComponent = SH.term('JSConstraintComponent')


class JSExecutable(object):
    __slots__ = ("sg","node","fn_name","libraries")


    def __init__(self, sg: 'ShapesGraph', node):
        self.node = node
        self.sg = sg
        fn_names = set(sg.objects(node, SH_jsFunctionName))
        if len(fn_names) < 1:
            raise ConstraintLoadError(
                "At least one sh:jsFunctionName must be present on a JS Executable.",
                "https://www.w3.org/TR/shacl-js/#dfn-javascript-executables",
            )
        elif len(fn_names) > 1:
            raise ConstraintLoadError(
                "At most one sh:jsFunctionName can be present on a JS Executable.",
                "https://www.w3.org/TR/shacl-js/#dfn-javascript-executables",
            )
        fn_name = next(iter(fn_names))
        if not isinstance(fn_name, Literal):
            raise ConstraintLoadError(
                "sh:jsFunctionName must be an RDF Literal with type xsd:string.",
                "https://www.w3.org/TR/shacl-js/#dfn-javascript-executables",
            )
        else:
            fn_name = str(fn_name)
        self.fn_name = fn_name
        library_defs = sg.objects(node, SH_jsLibrary)
        seen_library_defs = []
        libraries = {}
        for libn in library_defs:
            if libn in seen_library_defs:
                continue
            if isinstance(libn, Literal):
                raise ConstraintLoadError(
                    "sh:jsLibrary must not have a value that is a Literal.",
                    "https://www.w3.org/TR/shacl-js/#dfn-javascript-executables",
                )
            seen_library_defs.append(libn)
            jsLibraryURLs = list(sg.objects(libn, SH_jsLibraryURL))
            if len(jsLibraryURLs) > 0:
                libraries[libn] = libraries.get(libn, [])
            for u in jsLibraryURLs:
                if not isinstance(u, Literal):
                    raise ConstraintLoadError(
                        "sh:jsLibraryURL must have a value that is a Literal.",
                        "https://www.w3.org/TR/shacl-js/#dfn-javascript-executables",
                    )
                libraries[libn].append(str(u))
            library_defs2 = sg.objects(libn, SH_jsLibrary)
            for libn2 in library_defs2:
                if libn2 in seen_library_defs:
                    continue
                if isinstance(libn2, Literal):
                    raise ConstraintLoadError(
                        "sh:jsLibrary must not have a value that is a Literal.",
                        "https://www.w3.org/TR/shacl-js/#dfn-javascript-executables",
                    )
                seen_library_defs.append(libn2)
                jsLibraryURLs2 = list(sg.objects(libn2, SH_jsLibraryURL))
                if len(jsLibraryURLs2) > 0:
                    libraries[libn2] = libraries.get(libn2, [])
                for u2 in jsLibraryURLs2:
                    if not isinstance(u2, Literal):
                        raise ConstraintLoadError(
                            "sh:jsLibraryURL must have a value that is a Literal.",
                            "https://www.w3.org/TR/shacl-js/#dfn-javascript-executables",
                        )
                    libraries[libn2].append(str(u2))
        self.libraries = libraries

    def execute(self, datagraph, *args, **kwargs):
        ctx = SHACLJSContext(self.sg, datagraph, **kwargs)
        for lib_node, lib_urls in self.libraries.items():
            for lib_url in lib_urls:
                ctx.load_js_library(lib_url)
        return ctx.run_js_function(self.fn_name, args)

class JSConstraint(ConstraintComponent):
    """
    sh:minCount specifies the minimum number of value nodes that satisfy the condition. If the minimum cardinality value is 0 then this constraint is always satisfied and so may be omitted.
    Link:
    https://www.w3.org/TR/shacl/#MinCountConstraintComponent
    Textual Definition:
    If the number of value nodes is less than $minCount, there is a validation result.
    """

    def __init__(self, shape):
        super(JSConstraint, self).__init__(shape)
        js_decls = list(self.shape.objects(SH_js))
        if len(js_decls) < 1:
            raise ConstraintLoadError(
                "JSConstraint must have at least one sh:js predicate.",
                "https://www.w3.org/TR/shacl-js/#js-constraints",
            )
        self.js_exes = [JSExecutable(shape.sg, j) for j in js_decls]

    @classmethod
    def constraint_parameters(cls):
        return [SH_js]

    @classmethod
    def constraint_name(cls):
        return "JSConstraint"

    @classmethod
    def shacl_constraint_class(cls):
        return SH_JSConstraint

    def make_generic_messages(self, datagraph: GraphLike, focus_node, value_node) -> List[Literal]:
        return [Literal("Javascript Function generated constraint validation reports.")]

    def evaluate(self, data_graph: GraphLike, focus_value_nodes: Dict, _evaluation_path: List):
        """
        :type data_graph: rdflib.Graph
        :type focus_value_nodes: dict
        :type _evaluation_path: list
        """
        reports = []
        non_conformant = False
        for c in self.js_exes:
            _n, _r = self._evaluate_js_exe(data_graph, focus_value_nodes, c)
            non_conformant = non_conformant or _n
            reports.extend(_r)
        return (not non_conformant), reports

    def _evaluate_js_exe(self, data_graph, f_v_dict, js_exe):
        reports = []
        non_conformant = False
        for f, value_nodes in f_v_dict.items():
            for v in value_nodes:
                failed = False
                try:
                    res = js_exe.execute(data_graph, f, v)
                    if isinstance(res, bool) and not res:
                        failed = True
                        reports.append(self.make_v_result(data_graph, f, value_node=v))
                    elif isinstance(res, str):
                        failed = True
                        m = Literal(res)
                        reports.append(self.make_v_result(data_graph, f, value_node=v, extra_messages=[m]))
                    elif isinstance(res, dict):
                        failed = True
                        val = res.get('value', None)
                        if val is None:
                            val = v
                        path = res.get('path', None) if not self.shape.is_property_shape else None
                        msgs = []
                        message = res.get('message', None)
                        if message is not None:
                            msgs.append(Literal(message))
                        reports.append(self.make_v_result(data_graph, f, value_node=val, result_path=path, extra_messages=msgs))
                    elif isinstance(res, list):
                        for r in res:
                            failed = True
                            if isinstance(r, bool) and not r:
                                reports.append(self.make_v_result(data_graph, f, value_node=v))
                            elif isinstance(r, str):
                                m = Literal(r)
                                reports.append(self.make_v_result(data_graph, f, value_node=v, extra_messages=[m]))
                            elif isinstance(r, dict):
                                val = r.get('value', None)
                                if val is None:
                                    val = v
                                path = r.get('path', None) if not self.shape.is_property_shape else None
                                msgs = []
                                message = r.get('message', None)
                                if message is not None:
                                    msgs.append(Literal(message))
                                reports.append(self.make_v_result(data_graph, f, value_node=val, result_path=path,
                                                                  extra_messages=msgs))
                except Exception as e:
                    raise
                if failed:
                    non_conformant = True
        return non_conformant, reports


class BoundShapeJSValidatorComponent(ConstraintComponent):
    invalid_parameter_names = {'this', 'shapesGraph', 'currentShape', 'path', 'PATH', 'value'}
    def __init__(self, constraint, shape: 'Shape', validator):
        """
        Create a new custom constraint, by applying a ConstraintComponent and a Validator to a Shape
        :param constraint: The source ConstraintComponent, this is needed to bind the parameters in the query_helper
        :type constraint: SPARQLConstraintComponent
        :param shape:
        :type shape: Shape
        :param validator:
        :type validator: AskConstraintValidator | SelectConstraintValidator
        """
        super(BoundShapeJSValidatorComponent, self).__init__(shape)
        self.constraint = constraint
        self.validator = validator
        self.param_bind_map = {}
        self.messages = []
        self.bind_params()

    def bind_params(self):
        bind_map = {}
        shape = self.shape
        for p in self.constraint.parameters:
            name = p.localname
            if name in self.invalid_parameter_names:
                # TODO:coverage: No test for this case
                raise ReportableRuntimeError("Parameter name {} cannot be used.".format(name))
            shape_params = set(shape.objects(p.path()))
            if len(shape_params) < 1:
                if not p.optional:
                    # TODO:coverage: No test for this case
                    raise ReportableRuntimeError(
                        "Shape does not have mandatory parameter {}.".format(str(p.path())))
                continue
            # TODO: Can shapes have more than one value for the predicate?
            # Just use one for now.
            # TODO: Check for sh:class and sh:nodeKind on the found param value
            bind_map[name] = next(iter(shape_params))
        self.param_bind_map = bind_map


    @classmethod
    def constraint_parameters(cls):
        # TODO:coverage: this is never used for this constraint?
        return []

    @classmethod
    def constraint_name(cls):
        return "ConstraintComponent"

    @classmethod
    def shacl_constraint_class(cls):
        # TODO:coverage: this is never used for this constraint?
        return SH_ConstraintComponent

    def evaluate(self, target_graph: GraphLike, focus_value_nodes: Dict, _evaluation_path: List):
        """
        :type focus_value_nodes: dict
        :type target_graph: rdflib.Graph
        """
        reports = []
        non_conformant = False
        extra_messages = self.messages or None
        rept_kwargs = {
            # TODO, determine if we need sourceConstraint here
            #  'source_constraint': self.validator.node,
            'constraint_component': self.constraint.node,
            'extra_messages': extra_messages,
        }
        for f, value_nodes in focus_value_nodes.items():
            # we don't use value_nodes in the sparql constraint
            # All queries are done on the corresponding focus node.
            try:
                violations = self.validator.validate(f, value_nodes, target_graph, self.param_bind_map)
            except ValidationFailure as e:
                raise e
            if not self.shape.is_property_shape:
                result_val = f
            else:
                result_val = None
            for v in violations:
                non_conformant = True
                if isinstance(v, bool) and v is True:
                    # TODO:coverage: No test for when violation is `True`
                    rept = self.make_v_result(target_graph, f, value_node=result_val, **rept_kwargs)
                elif isinstance(v, tuple):
                    t, p, v = v
                    if v is None:
                        v = result_val
                    rept = self.make_v_result(target_graph, t or f, value_node=v, result_path=p, **rept_kwargs)
                else:
                    rept = self.make_v_result(target_graph, f, value_node=v, **rept_kwargs)
                reports.append(rept)
        return (not non_conformant), reports

class JSConstraintComponent(CustomConstraintComponent):
    """
    SPARQL-based constraints provide a lot of flexibility but may be hard to understand for some people or lead to repetition. This section introduces SPARQL-based constraint components as a way to abstract the complexity of SPARQL and to declare high-level reusable components similar to the Core constraint components. Such constraint components can be declared using the SHACL RDF vocabulary and thus shared and reused.
    Link:
    https://www.w3.org/TR/shacl-js/#js-components
    """

    __slots__: Tuple = tuple()

    def __new__(cls, shacl_graph, node, parameters, validators, node_validators, property_validators):
        return super(JSConstraintComponent, cls).__new__(
            cls, shacl_graph, node, parameters, validators, node_validators, property_validators
        )

    def make_validator_for_shape(self, shape: 'Shape'):
        """
        :param shape:
        :type shape: Shape
        :return:
        """
        val_count = len(self.validators)
        node_val_count = len(self.node_validators)
        prop_val_count = len(self.property_validators)
        if shape.is_property_shape and prop_val_count > 0:
            validator_node = next(iter(self.property_validators))
        elif (not shape.is_property_shape) and node_val_count > 0:
            validator_node = next(iter(self.node_validators))
        elif val_count > 0:
            validator_node = next(iter(self.validators))
        else:
            raise ConstraintLoadError(
                "Cannot select a validator to use, according to the rules.",
                "https://www.w3.org/TR/shacl/#constraint-components-validators",
            )

        validator = JSConstraintComponentValidator(self.sg, validator_node)
        applied_validator = validator.apply_to_shape_via_constraint(self, shape)
        return applied_validator

class JSConstraintComponentValidator(object):
    validator_cache: Dict[Tuple[int, str], 'JSConstraintComponentValidator'] = {}

    def __new__(cls, shacl_graph: 'ShapesGraph', node, *args, **kwargs):
        cache_key = (id(shacl_graph.graph), str(node))
        found_in_cache = cls.validator_cache.get(cache_key, False)
        if found_in_cache:
            return found_in_cache
        self = super(JSConstraintComponentValidator, cls).__new__(cls)
        cls.validator_cache[cache_key] = self
        return self

    def __init__(self, shacl_graph: 'ShapesGraph', node, *args, **kwargs):
        initialised = getattr(self, 'initialised', False)
        if initialised:
            return
        self.shacl_graph = shacl_graph
        self.node = node
        sg = shacl_graph.graph
        message_nodes = set(sg.objects(node, SH_message))
        for m in message_nodes:
            if not (isinstance(m, Literal) and isinstance(m.value, str)):
                # TODO:coverage: No test for when SPARQL-based constraint is RDF Literal is is not of type string
                raise ConstraintLoadError(
                    "Validator sh:message must be an RDF Literal of type xsd:string.",
                    "https://www.w3.org/TR/shacl/#ConstraintComponent",
                )
        self.messages = message_nodes
        self.js_exe = JSExecutable(shacl_graph, node)
        self.initialised = True

    def validate(self, focus, value_nodes, target_graph, param_bind_vals, new_bind_vals=None):
        """

        :param focus:
        :param value_nodes:
        :param query_helper:
        :param target_graph:
        :type target_graph: rdflib.Graph
        :param new_bind_vals:
        :return:
        """
        new_bind_vals = new_bind_vals or {}
        bind_vals = param_bind_vals.copy()
        bind_vals.update(new_bind_vals)
        for v in value_nodes:
            # bind v, and bind_vals
            args = [v, bind_vals['maxLength']]
            # TODO: Determine which variables the fn takes, and determine the order it takes them
            results = self.js_exe.execute(target_graph, *args)
            if not results or len(results.bindings) < 1:
                return []
            violations = set()
            for r in results:
                try:
                    p = r['path']
                except KeyError:
                    p = None
                try:
                    v = r['value']
                except KeyError:
                    v = None
                try:
                    t = r['this']
                except KeyError:
                    # TODO:coverage: No test for when result has no 'this' key
                    t = None
                if p or v or t:
                    violations.add((t, p, v))
                else:
                    # TODO:coverage: No test for generic failure, when
                    #  'path' and 'value' and 'this' are not returned.
                    #  here 'failure' must exist
                    try:
                        _ = r['failure']
                        violations.add(True)
                    except KeyError:
                        pass
            return violations

    def apply_to_shape_via_constraint(self, constraint, shape, **kwargs) -> BoundShapeJSValidatorComponent:
        """
        Create a new Custom Constraint (BoundShapeValidatorComponent)
        :param constraint:
        :type constraint: SPARQLConstraintComponent
        :param shape:
        :type shape: pyshacl.shape.Shape
        :param kwargs:
        :return:
        """
        return BoundShapeJSValidatorComponent(constraint, shape, self)
