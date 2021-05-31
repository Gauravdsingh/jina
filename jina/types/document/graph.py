from typing import Optional, Iterator, Tuple, Dict, Iterable

import numpy as np

from . import Document, DocumentSourceType
from ..arrays import ChunkArray
from ..struct import StructView
from ..ndarray.sparse.scipy import SparseNdArray
from ...logging.predefined import default_logger


__all__ = ['GraphDocument']

if False:
    from scipy.sparse import coo_matrix


class GraphDocument(Document):
    """
    :class:`GraphDocument` is a data type created based on Jina primitive data type :class:`Document`.

    It adds functionality that lets you work with a `Document` as a `graph` where all its chunks are the nodes in the `graph`.

    It exposes functionality to access and manipulate `graph related info` from the `DocumentProto` such as adjacency and edge features.

    .. warning::
        - It assumes that every ``chunk`` of a ``document`` is a node of a graph.

    :param document: the document to construct from. If ``bytes`` is given
            then deserialize a :class:`DocumentProto`; ``dict`` is given then
            parse a :class:`DocumentProto` from it; ``str`` is given, then consider
            it as a JSON string and parse a :class:`DocumentProto` from it; finally,
            one can also give `DocumentProto` directly, then depending on the ``copy``,
            it builds a view or a copy from it.
    :param copy: when ``document`` is given as a :class:`DocumentProto` object, build a
            view (i.e. weak reference) from it or a deep copy from it.
    :param kwargs: further key value arguments
    """

    def __init__(
        self,
        document: Optional[DocumentSourceType] = None,
        copy: bool = False,
        **kwargs,
    ):
        super().__init__(document=document, copy=copy, **kwargs)
        self._chunk_id_to_offset = {
            chunk.id: offset for offset, chunk in enumerate(self.chunks)
        }

    def add_node(self, node: 'Document'):
        """
        Add a a node to the graph

        :param node: the node to be added to the graph
        """
        if node.id in self._chunk_id_to_offset:
            default_logger.warning(f'Document {node.id} is already a node of the graph')
            return

        self._chunk_id_to_offset[node.id] = len(self.chunks)
        self.chunks.append(node)

    def add_edge(
        self, doc1: 'Document', doc2: 'Document', features: Optional[Dict] = None
    ):
        """
        Add an edge to the graph connecting `doc1` with `doc2`

        :param doc1: the starting node for this edge
        :param doc2: the ending node for this edge
        :param features: Optional features dictionary to be added to this new created edge
        """
        from scipy.sparse import coo_matrix

        for doc in [doc1, doc2]:
            self.add_node(doc)

        current_adjacency = self.adjacency
        doc1_node_offset = self._chunk_id_to_offset[doc1.id]
        doc2_node_offset = self._chunk_id_to_offset[doc2.id]
        row = (
            np.append(current_adjacency.row, doc1_node_offset)
            if current_adjacency is not None
            else np.array([doc1_node_offset])
        )
        col = (
            np.append(current_adjacency.col, doc2_node_offset)
            if current_adjacency is not None
            else np.array([doc2_node_offset])
        )
        data = (
            np.append(current_adjacency.data, 1)
            if current_adjacency is not None
            else np.array([1])
        )
        self.adjacency = coo_matrix((data, (row, col)))
        if features is not None:
            self.edge_features[len(self.adjacency)] = features

    @property
    def edge_features(self):
        """
        The dictionary of edge features, indexed by `edge_id` in the `edge list`

        .. # noqa: DAR201
        """
        return StructView(self._pb_body.graph_info.edge_features)

    @edge_features.setter
    def edge_features(self, value: Dict):
        """Set the `edge_features` field of this Graph to a Python dict

        :param value: a Python dict
        """
        self._pb_body.graph_info.edge_features.Clear()
        self._pb_body.graph_info.edge_features.update(value)

    @property
    def adjacency(self):
        """
        The adjacency list for this graph,

        .. # noqa: DAR201
        """
        return SparseNdArray(self._pb_body.graph_info.adjacency, sp_format='coo').value

    @adjacency.setter
    def adjacency(self, value: 'coo_matrix'):
        """
        Set the adjacency list of this graph.

        :param value: the float weight of the document.
        """
        SparseNdArray(self._pb_body.graph_info.adjacency, sp_format='coo').value = value

    def get_out_degree(self, doc: 'Document') -> int:
        """
        The out degree of the doc node

        .. # noqa: DAR201
        :param doc: the document node from which to extract the outdegree.
        """
        out_edges = self.get_outgoing_nodes(doc)
        return len(out_edges) if out_edges else 0

    def get_in_degree(self, doc: 'Document') -> int:
        """
        The in degree of the doc node

        .. # noqa: DAR201
        :param doc: the document node from which to extract the indegree.
        """
        in_edges = self.get_incoming_nodes(doc)
        return len(in_edges) if in_edges else 0

    @property
    def num_nodes(self) -> int:
        """
        The number of nodes in the graph

        .. # noqa: DAR201
        """
        return len(self.nodes)

    @property
    def num_edges(self) -> int:
        """
        The number of edges in the graph

        .. # noqa: DAR201
        """
        adjacency = self.adjacency
        return len(adjacency.data) if adjacency is not None else 0

    @property
    def nodes(self):
        """
        The nodes list for this graph

        .. # noqa: DAR201
        """
        return self.chunks

    @nodes.setter
    def nodes(self, value: Iterable['Document']):
        """Set all nodes of the current document.

        :param value: the array of nodes of this document
        """
        self.chunks = value

    @adjacency.setter
    def adjacency(self, value: 'coo_matrix'):
        """
        Set the adjacency list of this graph.

        :param value: the float weight of the document.
        """
        SparseNdArray(self._pb_body.graph_info.adjacency, sp_format='coo').value = value

    def get_outgoing_nodes(self, doc: 'Document') -> Optional[ChunkArray]:
        """
        Get all the outgoing edges from `doc`

        .. # noqa: DAR201
        :param doc: the document node from which to extract the outgoing nodes.
        """
        if self.adjacency is not None and doc.id in self._chunk_id_to_offset:
            offset = self._chunk_id_to_offset[doc.id]
            return ChunkArray(
                [
                    self.chunks[col.item()]
                    for (row, col) in zip(self.adjacency.row, self.adjacency.col)
                    if row.item() == offset
                ],
                reference_doc=self,
            )

    def get_incoming_nodes(self, doc: 'Document') -> Optional[ChunkArray]:
        """
        Get all the outgoing edges from `doc`

        .. # noqa: DAR201
        :param doc: the document node from which to extract the incoming nodes.
        """
        if self.adjacency is not None and doc.id in self._chunk_id_to_offset:
            offset = self._chunk_id_to_offset[doc.id]
            return ChunkArray(
                [
                    self.chunks[row.item()]
                    for (row, col) in zip(self.adjacency.row, self.adjacency.col)
                    if col.item() == offset
                ],
                reference_doc=self,
            )

    def __iter__(self) -> Iterator[Tuple['Document']]:
        for (row, col) in zip(self.adjacency.row, self.adjacency.col):
            yield self.chunks[row.item()], self.chunks[col.item()]

    def __len__(self) -> int:
        return self.adjacency.getnnz()