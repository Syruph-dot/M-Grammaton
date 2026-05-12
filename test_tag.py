"""测试：标签系统 —— tag_manager.TagManager。"""

from tag_manager import TagManager
from mgraph import MGraph, Node


class TestTagManagerCore:
    def test_add_tag(self):
        mgr = TagManager()
        assert mgr.add_tag("epistemology") is True
        assert mgr.add_tag("epistemology") is False  # 重复添加
        assert mgr.tag_exists("epistemology")

    def test_add_tag_empty_name_raises(self):
        mgr = TagManager()
        try:
            mgr.add_tag("")
            assert False, "should have raised"
        except ValueError:
            pass

    def test_remove_tag(self):
        mgr = TagManager()
        mgr.add_tag("ontology")
        assert mgr.remove_tag("ontology") is True
        assert mgr.tag_exists("ontology") is False
        assert mgr.remove_tag("nonexistent") is False

    def test_rename_tag(self):
        mgr = TagManager()
        mgr.add_tag("old", aliases=["o"])
        mgr.link_node("old", "node_1")
        assert mgr.rename_tag("old", "new") is True
        assert mgr.tag_exists("new")
        assert mgr.tag_exists("old") is False
        assert mgr.get_nodes_for_tag("new") == ["node_1"]


class TestTagAliases:
    def test_add_alias(self):
        mgr = TagManager()
        mgr.add_tag("epistemology")
        assert mgr.add_alias("epistemology", "认识论") is True
        # 通过别名解析
        assert mgr.tag_exists("认识论")

    def test_add_alias_to_nonexistent_tag(self):
        mgr = TagManager()
        assert mgr.add_alias("nonexistent", "alias") is False

    def test_remove_alias(self):
        mgr = TagManager()
        mgr.add_tag("epistemology", aliases=["认识论"])
        assert mgr.remove_alias("epistemology", "认识论") is True
        assert not mgr.tag_exists("认识论")

    def test_get_aliases(self):
        mgr = TagManager()
        mgr.add_tag("ontology", aliases=["本体论", "ont"])
        aliases = mgr.get_aliases("ontology")
        assert "本体论" in aliases
        assert "ont" in aliases


class TestNodeTagLink:
    def test_link_node(self):
        mgr = TagManager()
        mgr.add_tag("touhou")
        assert mgr.link_node("touhou", "dopp62") is True
        assert mgr.get_nodes_for_tag("touhou") == ["dopp62"]

    def test_link_node_via_alias(self):
        mgr = TagManager()
        mgr.add_tag("touhou", aliases=["东方"])
        assert mgr.link_node("东方", "dopp62") is True
        assert "dopp62" in mgr.get_nodes_for_tag("touhou")

    def test_unlink_node(self):
        mgr = TagManager()
        mgr.add_tag("touhou")
        mgr.link_node("touhou", "dopp62")
        assert mgr.unlink_node("touhou", "dopp62") is True
        assert mgr.get_nodes_for_tag("touhou") == []

    def test_link_nonexistent_tag(self):
        mgr = TagManager()
        assert mgr.link_node("nonexistent", "node_1") is False


class TestConceptTags:
    def test_add_conc_tag(self):
        mgr = TagManager()
        mgr.add_tag("epistemology")
        mgr.add_tag("ontology")
        assert mgr.add_conc_tag("epistemology", "ontology", weight=3) is True
        conc = mgr.get_conc_tags("epistemology")
        assert conc.get("ontology") == 3

    def test_conc_tag_is_bidirectional(self):
        mgr = TagManager()
        mgr.add_tag("a")
        mgr.add_tag("b")
        mgr.add_conc_tag("a", "b", 2)
        assert mgr.get_conc_tags("b").get("a") == 2

    def test_remove_conc_tag(self):
        mgr = TagManager()
        mgr.add_tag("a")
        mgr.add_tag("b")
        mgr.add_conc_tag("a", "b", 1)
        assert mgr.remove_conc_tag("a", "b") is True
        assert mgr.get_conc_tags("a") == {}

    def test_conc_tag_self_rejected(self):
        mgr = TagManager()
        mgr.add_tag("a")
        assert mgr.add_conc_tag("a", "a", 1) is False


class TestSerialization:
    def test_to_dict_roundtrip(self):
        mgr = TagManager()
        mgr.add_tag("touhou", aliases=["东方"])
        mgr.add_tag("哲学", aliases=["philosophy"])
        mgr.link_node("touhou", "dopp62")
        mgr.add_conc_tag("touhou", "哲学", weight=2)

        data = mgr.to_dict()
        mgr2 = TagManager.from_dict(data)
        assert mgr2.tag_exists("touhou")
        assert mgr2.tag_exists("东方")
        assert mgr2.get_nodes_for_tag("touhou") == ["dopp62"]
        assert mgr2.get_conc_tags("touhou").get("哲学") == 2

    def test_empty_serialization(self):
        data = TagManager().to_dict()
        mgr = TagManager.from_dict(data)
        assert mgr.get_all_tags() == []


class TestGraphRebuild:
    def test_rebuild_from_graph(self):
        g = MGraph()
        g.add_node(Node("node_a", tags={"touhou", "东方"}, mg=g))
        g.add_node(Node("node_b", tags={"哲学"}, mg=g))

        mgr = TagManager()
        mgr.rebuild_from_graph(g)

        assert mgr.tag_exists("touhou")
        assert mgr.tag_exists("哲学")
        assert mgr.get_nodes_for_tag("touhou") == ["node_a"]
        assert mgr.get_nodes_for_tag("哲学") == ["node_b"]

    def test_rebuild_preserves_orphan_tags(self):
        """重建时，不再出现在任何节点上的标签应保留（一等实体）。"""
        g = MGraph()
        g.add_node(Node("node_a", tags={"temp"}, mg=g))

        mgr = TagManager()
        mgr.rebuild_from_graph(g)
        assert mgr.get_nodes_for_tag("temp") == ["node_a"]

        # 移除节点，重建——标签仍存在但无关联节点
        g.V.clear()
        mgr.rebuild_from_graph(g)
        assert mgr.tag_exists("temp")
        assert mgr.get_nodes_for_tag("temp") == []


class TestGetAllTags:
    def test_get_all_tags_format(self):
        mgr = TagManager()
        mgr.add_tag("touhou", aliases=["东方"])
        mgr.link_node("touhou", "dopp62")

        tags = mgr.get_all_tags()
        assert len(tags) == 1
        assert tags[0]["name"] == "touhou"
        assert tags[0]["nodes"] == 1
        assert "东方" in tags[0]["aliases"]


class TestGetNodeTags:
    def test_get_node_tags(self):
        mgr = TagManager()
        mgr.add_tag("a")
        mgr.add_tag("b")
        mgr.link_node("a", "node_x")
        mgr.link_node("b", "node_x")
        assert mgr.get_node_tags("node_x") == ["a", "b"]

    def test_get_node_tags_none(self):
        mgr = TagManager()
        assert mgr.get_node_tags("nonexistent") == []


class TestAllConcEdges:
    def test_get_all_conc_edges(self):
        mgr = TagManager()
        mgr.add_tag("a")
        mgr.add_tag("b")
        mgr.add_tag("c")
        mgr.add_conc_tag("a", "b", 3)
        mgr.add_conc_tag("a", "c", 1)

        edges = mgr.get_all_conc_edges()
        assert len(edges) == 2
        pairs = {(e["source"], e["target"]) for e in edges}
        assert ("a", "b") in pairs or ("b", "a") in pairs
        assert ("a", "c") in pairs or ("c", "a") in pairs
        # 验证无重复边
        for e in edges:
            rev = (e["target"], e["source"])
            assert rev not in pairs or (e["source"], e["target"]) in pairs, \
                f"duplicate edge: {e}"
