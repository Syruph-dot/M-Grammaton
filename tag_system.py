from mgraph import Node, Edge
class Tag():
    def __init__(self, name: str):
        self.name = name
        self.outlinks:list[Node]=[]
        self.conc_tags:dict[Tag,int]={}
        self.aliases:list[Tag]=[]