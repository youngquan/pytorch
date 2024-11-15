# Owner(s): ["module: onnx"]
"""Unit tests for the _building module."""

from __future__ import annotations

import os
import tempfile

import onnx

import torch
from torch.onnx._internal.exporter import _compat
from torch.testing._internal import common_utils


class SampleModelForDynamicShapes(torch.nn.Module):
    def forward(self, x, b):
        return x.relu(), b.sigmoid()


class NestedModelForDynamicShapes(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.u = torch.nn.Buffer(torch.ones(1))
        self.v = torch.nn.Buffer(torch.ones(1))

    def forward(self, x, ys, zs, c):
        y = ys[0] + ys[1] + zs["a"] + zs["b"]
        self.v.add_(3)
        w = self.u - self.v
        if x.shape[0] < 3 and c.shape[0] != 4:
            return x + w, x + y
        else:
            return x - w, x - y


@common_utils.instantiate_parametrized_tests
class TestCompat(common_utils.TestCase):
    @common_utils.parametrize(
        "dynamic_shapes, input_names, expected_dynamic_axes",
        [
            (
                {
                    "input_x": {
                        0: torch.export.Dim("customx_dim_0"),
                        1: torch.export.Dim("customx_dim_1"),
                    },
                    "input_b": {0: torch.export.Dim("customb_dim_0")},
                },
                None,
                {
                    "input_x": {0: "customx_dim_0", 1: "customx_dim_1"},
                    "input_b": {0: "customb_dim_0"},
                },
            ),
            (
                (
                    {
                        0: torch.export.Dim("customx_dim_0"),
                        1: torch.export.Dim("customx_dim_1"),
                    },
                    {
                        0: torch.export.Dim("customb_dim_0"),
                        1: None,
                        2: torch.export.Dim("customb_dim_2"),
                    },
                ),
                ["input_x", "input_b"],
                {
                    "input_x": {0: "customx_dim_0", 1: "customx_dim_1"},
                    "input_b": {0: "customb_dim_0", 2: "customb_dim_2"},
                },
            ),
            (
                (
                    {
                        0: torch.export.Dim("customx_dim_0"),
                        1: torch.export.Dim("customx_dim_1"),
                    },
                ),
                ["x"],
                {
                    "x": {0: "customx_dim_0", 1: "customx_dim_1"},
                },
            ),
        ],
    )
    def test_from_dynamic_shapes_to_dynamic_axes_success(
        self, dynamic_shapes, input_names, expected_dynamic_axes
    ):
        dynamic_axes = _compat._from_dynamic_shapes_to_dynamic_axes(
            dynamic_shapes=dynamic_shapes, input_names=input_names
        )
        self.assertEqual(dynamic_axes, expected_dynamic_axes)

    def test_dynamic_shapes_supports_nested_input_model_with_input_names_assigned(self):
        dim = torch.export.Dim("dim", min=3)
        dynamic_shapes = (
            {0: dim},
            [{0: dim}, {0: dim}],
            {"a": {0: dim}, "b": {0: dim}},
            None,
        )
        # kwargs can still be renamed as long as it's in order
        input_names = ["input_x", "input_y", "input_z", "d", "e", "f"]
        dynamic_axes = _compat._from_dynamic_shapes_to_dynamic_axes(
            dynamic_shapes=dynamic_shapes, input_names=input_names
        )
        expected_dynamic_axes = {
            "input_x": {0: "dim"},
            "input_y": {0: "dim"},
            "input_z": {0: "dim"},
            "d": {0: "dim"},
            "e": {0: "dim"},
        }
        self.assertEqual(dynamic_axes, expected_dynamic_axes)

        model = NestedModelForDynamicShapes()
        input = (
            torch.ones(5),
            [torch.zeros(5), torch.ones(5)],
            {"a": torch.zeros(5), "b": torch.ones(5)},
            torch.ones(4),
        )

        with tempfile.TemporaryDirectory() as temp:
            filename = os.path.join(temp, "model.onnx")
            torch.onnx.export(
                model,
                input,
                filename,
                dynamic_axes=dynamic_axes,
                input_names=input_names,
            )
            onnx_model = onnx.load(filename)

        self.assertTrue(
            all(
                input.type.tensor_type.shape.dim[0].dim_param
                for input in onnx_model.graph.input
            )
        )


if __name__ == "__main__":
    common_utils.run_tests()
# Owner(s): ["module: onnx"]
"""Unit tests for the _compat module."""

from __future__ import annotations

import torch
from torch.onnx._internal.exporter import _compat
from torch.testing._internal import common_utils
from torch.utils import _pytree


class SingnatureOnlyLlamaModel(torch.nn.Module):
    def forward(
        self,
        input_ids: torch.LongTensor = None,
        attention_mask: torch.Tensor | None = None,
        position_ids: torch.LongTensor | None = None,
        past_key_values: list[torch.FloatTensor] | None = None,
        inputs_embeds: torch.FloatTensor | None = None,
        labels: torch.LongTensor | None = None,
        use_cache: bool | None = None,
        output_attentions: bool | None = None,
        output_hidden_states: bool | None = None,
        return_dict: bool | None = None,
        cache_position: torch.LongTensor | None = None,
        num_logits_to_keep: int = 0,
        **kwargs,
    ):
        pass


@common_utils.instantiate_parametrized_tests
class TestPyTreeDynamicAxesShapes(common_utils.TestCase):
    # The test can't be parametrized because the torch.export.Dim generates objects,
    # and we need the exact same object to compare them.
    def test__unflatten_dynamic_shapes_with_inputs_tree_succeeds_on_tuple(self):
        inputs = (torch.randn(1, 2, 3), torch.randn(1, 2, 3))
        x_dim = torch.export.Dim("x_dim_0")
        y_dim = torch.export.Dim("y_dim_1")
        dynamic_shapes = {
            "x": {0: x_dim},
            "y": {1: y_dim},
        }
        unflatten_dynamic_shapes = _compat._unflatten_dynamic_shapes_with_inputs_tree(
            inputs, dynamic_shapes
        )

        expected_dynamic_shapes = (
            {0: x_dim},
            {1: y_dim},
        )
        self.assertEqual(unflatten_dynamic_shapes, expected_dynamic_shapes)

    def test__unflatten_dynamic_shapes_with_inputs_tree_succeeds_on_dict(self):
        inputs = {"x": torch.randn(1, 2, 3), "y": torch.randn(1, 2, 3)}
        x_dim = torch.export.Dim("x_dim_0")
        y_dim = torch.export.Dim("y_dim_1")
        dynamic_shapes = {
            "x": {0: x_dim},
            "y": {1: y_dim},
        }
        unflatten_dynamic_shapes = _compat._unflatten_dynamic_shapes_with_inputs_tree(
            inputs, dynamic_shapes
        )

        expected_dynamic_shapes = {
            "x": {0: x_dim},
            "y": {1: y_dim},
        }
        self.assertEqual(unflatten_dynamic_shapes, expected_dynamic_shapes)

    def test__unflatten_dynamic_shapes_with_inputs_tree_succeeds_on_tuple_of_mixed_structure(
        self,
    ):
        inputs = (
            torch.randn(1, 2, 3),
            ({"x0": torch.randn(1, 2, 3)}, {"x1": torch.randn(1, 2, 3)}),
            (torch.randn(1, 2, 3), torch.randn(1, 2, 3)),
            [torch.randn(1, 2, 3), torch.randn(1, 2, 3)],
        )
        w_dim_0 = torch.export.Dim("w_dim_0")
        x0_dim_1 = torch.export.Dim("x0_dim_1")
        x0_dim_2 = torch.export.Dim("x0_dim_2")
        x1_dim_1 = torch.export.Dim("x1_dim_1")
        y0_dim_0 = torch.export.Dim("y0_dim_0")
        y0_dim_1 = torch.export.Dim("y0_dim_1")
        y1_dim_2 = torch.export.Dim("y1_dim_2")
        z0_dim_2 = torch.export.Dim("z0_dim_2")
        z1_dim_1 = torch.export.Dim("z1_dim_1")
        dynamic_shapes = {
            "w": {0: w_dim_0},
            "x0": {1: x0_dim_1, 2: x0_dim_2},
            "x1": {1: x1_dim_1},
            "y0": {0: y0_dim_0, 1: y0_dim_1},
            "y1": {2: y1_dim_2},
            "z0": {2: z0_dim_2},
            "z1": {1: z1_dim_1},
        }
        unflatten_dynamic_shapes = _compat._unflatten_dynamic_shapes_with_inputs_tree(
            inputs, dynamic_shapes
        )
        expected_dynamic_shapes = (
            {0: w_dim_0},
            ({"x0": {1: x0_dim_1, 2: x0_dim_2}}, {"x1": {1: x1_dim_1}}),
            ({0: y0_dim_0, 1: y0_dim_1}, {2: y1_dim_2}),
            [{2: z0_dim_2}, {1: z1_dim_1}],
        )
        self.assertEqual(unflatten_dynamic_shapes, expected_dynamic_shapes)

    @common_utils.parametrize(
        "model, args, kwargs,input_names, output_names, dynamic_axes, expected_dynamic_shapes",
        [
            # llama-3.2-1B-Instruct (trimmed)
            (
                SingnatureOnlyLlamaModel(),
                (),
                {
                    "input_ids": torch.randn(2, 16),
                    "attention_mask": torch.randn(2, 32),
                    "position_ids": torch.randn(2, 16),
                    "past_key_values": [
                        (torch.randn(2, 8, 16, 64), torch.randn(2, 8, 16, 64)),
                        (torch.randn(2, 8, 16, 64), torch.randn(2, 8, 16, 64)),
                    ],
                },
                [
                    "input_ids",
                    "attention_mask",
                    "position_ids",
                    "past_key_values.0.key",
                    "past_key_values.0.value",
                    "past_key_values.1.key",
                    "past_key_values.1.value",
                ],
                [
                    "logits",
                    "present.0.key",
                    "present.0.value",
                    "present.1.key",
                    "present.1.value",
                ],
                {
                    "input_ids": {0: "batch_size", 1: "sequence_length"},
                    "attention_mask": {
                        0: "batch_size",
                        1: "past_sequence_length + sequence_length",
                    },
                    "position_ids": {0: "batch_size", 1: "sequence_length"},
                    "past_key_values.0.key": {
                        0: "batch_size",
                        2: "past_sequence_length",
                    },
                    "past_key_values.0.value": {
                        0: "batch_size",
                        2: "past_sequence_length",
                    },
                    "past_key_values.1.key": {
                        0: "batch_size",
                        2: "past_sequence_length",
                    },
                    "past_key_values.1.value": {
                        0: "batch_size",
                        2: "past_sequence_length",
                    },
                    "logits": {0: "batch_size", 1: "sequence_length"},
                    "present.0.key": {
                        0: "batch_size",
                        2: "past_sequence_length + sequence_length",
                    },
                    "present.0.value": {
                        0: "batch_size",
                        2: "past_sequence_length + sequence_length",
                    },
                    "present.1.key": {
                        0: "batch_size",
                        2: "past_sequence_length + sequence_length",
                    },
                    "present.1.value": {
                        0: "batch_size",
                        2: "past_sequence_length + sequence_length",
                    },
                },
                [
                    {
                        0: torch.export.Dim("batch_size"),
                        1: torch.export.Dim("sequence_length"),
                    },
                    {
                        0: torch.export.Dim("batch_size"),
                        1: torch.export.Dim("past_sequence_lengthsequence_length"),
                    },
                    {
                        0: torch.export.Dim("batch_size"),
                        1: torch.export.Dim("sequence_length"),
                    },
                    [
                        (
                            {
                                0: torch.export.Dim("batch_size"),
                                2: torch.export.Dim("past_sequence_length"),
                            },
                            {
                                0: torch.export.Dim("batch_size"),
                                2: torch.export.Dim("past_sequence_length"),
                            },
                        ),
                        (
                            {
                                0: torch.export.Dim("batch_size"),
                                2: torch.export.Dim("past_sequence_length"),
                            },
                            {
                                0: torch.export.Dim("batch_size"),
                                2: torch.export.Dim("past_sequence_length"),
                            },
                        ),
                    ],
                ],
            )
        ],
    )
    def test__from_dynamic_axes_to_dynamic_shapes_succeeds_on_llm(
        self,
        model,
        args,
        kwargs,
        input_names,
        output_names,
        dynamic_axes,
        expected_dynamic_shapes,
    ):
        dynamic_shapes = _compat._from_dynamic_axes_to_dynamic_shapes(
            model,
            args,
            kwargs,
            input_names=input_names,
            output_names=output_names,
            dynamic_axes=dynamic_axes,
        )

        # NOTE: torch.export.Dim being an object makes it impossible to compare the objects directly.
        # And it's unrealistic to test whole model, so we are testing the structure of the dynamic_shapes.
        _, tree1 = _pytree.tree_flatten(dynamic_shapes)
        _, tree2 = _pytree.tree_flatten(expected_dynamic_shapes)
        self.assertEqual(tree1, tree2)


if __name__ == "__main__":
    common_utils.run_tests()
