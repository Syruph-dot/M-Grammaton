from mgraph import MGraph, Node
from operators import Operator
from persistence import save_graph
from quest_board import QuestBoard
from runtime.runtime import OperatorRuntime


def test_operator_runtime_loads_split_persistence(tmp_path):
    data_dir = tmp_path / "data"
    graph = MGraph()
    source = graph.add_node(Node("source", content="human original", mg=graph))
    board = QuestBoard()
    operators = {"Alice": Operator("Alice", source)}
    save_graph(graph, board, operators, str(data_dir))

    runtime = OperatorRuntime(
        data_dir=str(data_dir),
        model="test-model",
        operator_names=["Alice"],
    )

    loaded = {node.name: node for node in runtime.graph.V}
    assert loaded["source"].content == "human original"
    assert runtime.operators["Alice"].current.get().name == "source"
