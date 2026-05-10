from mgraph import Node, Edge
from random import randint
class QuestNode(Node):
    def __init__(self, name: str,quester_id:str,content:str="This is a test quest node{}".format(randint(0, 1000))):
        super().__init__(name)
        self.name = name
        self.quester_id = quester_id
        self.content = content
        self.answers:list[str]=[]
        self.scores:list[tuple[float, float]]=[]
        self.from_ids:list[str]=[]
