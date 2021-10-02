from http import HTTPStatus
from pytest_kind import cluster

# kind version has to be bumped to v0.11.1 since pytest-kind is just using v0.10.0 which does not work on ubuntu in ci
# TODO don't use pytest-kind anymore
cluster.KIND_VERSION = 'v0.11.1'
import pytest
import requests

from jina import Flow


def pull_images(images, cluster, logger):
    # image pull anyways must be Never or IfNotPresent otherwise kubernetes will try to pull the image anyway
    logger.debug(f'Loading docker image into kind cluster...')
    for image in images:
        cluster.load_docker_image(image)
    cluster.load_docker_image('jinaai/jina:test-pip')
    logger.debug(f'Done loading docker image into kind cluster...')


def run_test(images, cluster, flow, logger, endpoint, port_expose):
    pull_images(images, cluster, logger)
    start_flow(flow, logger)
    resp = send_dummy_request(endpoint, cluster, flow, logger, port_expose=port_expose)
    return resp


def send_dummy_request(endpoint, k8s_cluster, k8s_flow_with_needs, logger, port_expose):
    logger.debug(f'Starting port-forwarding to gateway service...')
    with k8s_cluster.port_forward(
        'service/gateway', port_expose, port_expose, k8s_flow_with_needs.args.name
    ) as _:
        logger.debug(f'Port-forward running...')

        resp = requests.post(
            f'http://localhost:{port_expose}/{endpoint}',
            json={'data': [{} for _ in range(10)]},
        )
    return resp


def start_flow(flow, logger):
    logger.debug(f'Starting flow on kind cluster...')
    flow.start()
    logger.debug(f'Done starting flow on kind cluster...')


@pytest.fixture()
def k8s_flow_with_needs(test_executor_image: str, executor_merger_image: str) -> Flow:
    flow = (
        Flow(
            name='test-flow',
            port_expose=9090,
            infrastructure='K8S',
            protocol='http',
            timeout_ready=60000,
        )
        .add(
            name='segmenter',
            uses=test_executor_image,
            timeout_ready=60000,
        )
        .add(
            name='textencoder',
            uses=test_executor_image,
            needs='segmenter',
            timeout_ready=60000,
        )
        .add(
            name='textstorage',
            uses=test_executor_image,
            needs='textencoder',
            timeout_ready=60000,
        )
        .add(
            name='imageencoder',
            uses=test_executor_image,
            needs='segmenter',
            timeout_ready=60000,
        )
        .add(
            name='imagestorage',
            uses=test_executor_image,
            needs='imageencoder',
            timeout_ready=60000,
        )
        .add(
            name='merger',
            uses=executor_merger_image,
            timeout_ready=60000,
            needs=['imagestorage', 'textstorage'],
        )
    )
    return flow


@pytest.fixture()
def k8s_flow_with_init_container(
    test_executor_image: str, executor_merger_image: str, dummy_dumper_image: str
) -> Flow:
    flow = Flow(
        name='test-flow',
        port_expose=8080,
        infrastructure='K8S',
        protocol='http',
        timeout_ready=60000,
    ).add(
        name='test_executor',
        uses=test_executor_image,
        k8s_init_container_command=["python", "dump.py", "/shared/test_file.txt"],
        k8s_uses_init=dummy_dumper_image,
        k8s_mount_path='/shared',
        timeout_ready=60000,
    )
    return flow


@pytest.fixture()
def k8s_flow_with_sharding(
    test_executor_image: str, executor_merger_image: str, dummy_dumper_image: str
) -> Flow:
    flow = Flow(
        name='test-flow',
        port_expose=8080,
        infrastructure='K8S',
        protocol='http',
        timeout_ready=60000,
    ).add(
        name='test_executor',
        shards=3,
        replicas=2,
        uses=test_executor_image,
        uses_after=executor_merger_image,
        timeout_ready=60000,
    )
    return flow


@pytest.mark.timeout(3600)
@pytest.mark.parametrize('k8s_connection_pool', [True, False])
def test_flow_with_needs(
    k8s_cluster,
    test_executor_image,
    executor_merger_image,
    k8s_flow_with_needs: Flow,
    logger,
    k8s_connection_pool: bool,
):
    k8s_flow_with_needs.args.k8s_connection_pool = k8s_connection_pool
    resp = run_test(
        [test_executor_image, executor_merger_image],
        k8s_cluster,
        k8s_flow_with_needs,
        logger,
        endpoint='index',
        port_expose=9090,
    )

    expected_traversed_executors = {
        'segmenter',
        'imageencoder',
        'textencoder',
        'imagestorage',
        'textstorage',
    }

    assert resp.status_code == HTTPStatus.OK
    docs = resp.json()['data']['docs']
    assert len(docs) == 10
    for doc in docs:
        assert set(doc['tags']['traversed-executors']) == expected_traversed_executors


@pytest.mark.timeout(3600)
def test_flow_with_init(
    k8s_cluster,
    test_executor_image,
    dummy_dumper_image: str,
    k8s_flow_with_init_container: Flow,
    logger,
):
    resp = run_test(
        [test_executor_image, dummy_dumper_image],
        k8s_cluster,
        k8s_flow_with_init_container,
        logger,
        endpoint='search',
        port_expose=8080,
    )

    assert resp.status_code == HTTPStatus.OK
    docs = resp.json()['data']['docs']
    assert len(docs) == 10
    for doc in docs:
        assert doc['tags']['file'] == ['1\n', '2\n', '3']


@pytest.mark.timeout(3600)
def test_flow_with_sharding(
    k8s_cluster,
    test_executor_image,
    executor_merger_image,
    k8s_flow_with_sharding: Flow,
    logger,
):
    resp = run_test(
        [test_executor_image, executor_merger_image],
        k8s_cluster,
        k8s_flow_with_sharding,
        logger,
        endpoint='index',
        port_expose=8080,
    )

    expected_traversed_executors = {
        'test_executor',
    }

    assert resp.status_code == HTTPStatus.OK
    docs = resp.json()['data']['docs']
    assert len(docs) == 10
    for doc in docs:
        assert set(doc['tags']['traversed-executors']) == expected_traversed_executors
