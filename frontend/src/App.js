import React, { useState, useEffect } from 'react';
import { Container, Row, Col, Card, ListGroup, Spinner, Alert, Button, Modal, Form } from 'react-bootstrap';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  ArcElement, // Import ArcElement for Pie chart
} from 'chart.js';
import { Line, Pie } from 'react-chartjs-2'; // Import Pie for Pie chart
import './App.css';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  ArcElement // Register ArcElement
);

function App() {
  const [devices, setDevices] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState(null);
  const [deviceMetrics, setDeviceMetrics] = useState(null);
  const [metricHistory, setMetricHistory] = useState({}); // Stores historical data for charts
  const [selectedMetricForChart, setSelectedMetricForChart] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showAddDeviceModal, setShowAddDeviceModal] = useState(false);
  const [showEditDeviceModal, setShowEditDeviceModal] = useState(false);
  const [showDeleteConfirmModal, setShowDeleteConfirmModal] = useState(false);
  const [deviceToDelete, setDeviceToDelete] = useState(null);
  const [deviceToEdit, setDeviceToEdit] = useState(null);
  const [newDevice, setNewDevice] = useState({
    ip: '',
    name: '',
    community: 'public',
  });

  const API_BASE_URL = 'http://127.0.0.1:8000'; // FastAPI backend URL

  useEffect(() => {
    setLoading(true);
    const eventSource = new EventSource(`${API_BASE_URL}/devices/stream`);

    eventSource.onmessage = (event) => {
      const result = JSON.parse(event.data);

      if (result.event === 'initial') {
        setDevices(result.data);
        setLoading(false);
      } else if (result.event === 'update') {
        setDevices(prevDevices =>
          prevDevices.map(device =>
            device.id === result.data.id ? result.data : device
          )
        );
      } else if (result.event === 'reload') {
        fetchDevices();
      }
    };

    eventSource.onerror = (err) => {
      console.error("EventSource failed:", err);
      setError('Connection to server lost. Please refresh.');
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, []);

  const fetchDevices = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/devices`);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      setDevices(data);
    } catch (err) {
      setError('Failed to fetch devices: ' + err.message);
      console.error("Error fetching devices:", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchDeviceMetrics = async (deviceIp) => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/devices/${deviceIp}/metrics`);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      setDeviceMetrics(data.metrics);

      // Simulate historical data for charting
      const simulatedHistory = {};
      for (const key in data.metrics) {
        if (typeof data.metrics[key] === 'string' && data.metrics[key].endsWith('%')) {
          // For percentage metrics, generate random historical data
          simulatedHistory[key] = Array.from({ length: 10 }, (_, i) =>
            Math.floor(Math.random() * 100)
          );
        } else if (!isNaN(parseFloat(data.metrics[key]))) {
          // For numeric metrics, generate random historical data around the current value
          const currentValue = parseFloat(data.metrics[key]);
          simulatedHistory[key] = Array.from({ length: 10 }, (_, i) =>
            Math.max(0, Math.round(currentValue + (Math.random() - 0.5) * 20))
          );
        }
      }
      setMetricHistory(prev => ({ ...prev, [deviceIp]: simulatedHistory }));

    } catch (err) {
      setError('Failed to fetch device metrics: ' + err.message);
      console.error("Error fetching device metrics:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleDeviceClick = (device) => {
    setSelectedDevice(device);
    setDeviceMetrics(null); // Clear previous metrics
    setSelectedMetricForChart(null); // Clear previous chart selection
    fetchDeviceMetrics(device.ip);
  };

  const handleMetricClick = (metricKey) => {
    setSelectedMetricForChart(metricKey);
  };

  const handleAddDevice = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/devices`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(newDevice),
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }
      setShowAddDeviceModal(false);
      setNewDevice({ ip: '', name: '', community: 'public' });
    } catch (err) {
      setError('Failed to add device: ' + err.message);
      console.error("Error adding device:", err);
    }
  };

  const handleEditDevice = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/devices/${deviceToEdit.ip}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(deviceToEdit),
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }
      setShowEditDeviceModal(false);
      setDeviceToEdit(null);
    } catch (err) {
      setError('Failed to update device: ' + err.message);
      console.error("Error updating device:", err);
    }
  };

  const handleDeleteDevice = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/devices/${deviceToDelete.ip}`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }
      setShowDeleteConfirmModal(false);
      setDeviceToDelete(null);
      setSelectedDevice(null); // Clear selected device if deleted
    } catch (err) {
      setError('Failed to delete device: ' + err.message);
      console.error("Error deleting device:", err);
    }
  };

  const chartData = selectedDevice && selectedMetricForChart && metricHistory[selectedDevice.ip] && metricHistory[selectedDevice.ip][selectedMetricForChart] ? {
    labels: Array.from({ length: 10 }, (_, i) => `Time ${i + 1}`),
    datasets: [
      {
        label: selectedMetricForChart,
        data: metricHistory[selectedDevice.ip][selectedMetricForChart],
        fill: false,
        backgroundColor: 'rgb(75, 192, 192)',
        borderColor: 'rgba(75, 192, 192, 0.2)',
      },
    ],
  } : null;

  const chartOptions = {
    responsive: true,
    plugins: {
      legend: {
        position: 'top',
      },
      title: {
        display: true,
        text: `${selectedMetricForChart} for ${selectedDevice?.name || ''}`,
      },
    },
  };

  // Calculate online/offline counts for Pie chart
  const onlineCount = devices.filter(device => device.status === 'online').length;
  const offlineCount = devices.filter(device => device.status === 'offline').length;

  const pieChartData = {
    labels: ['Online', 'Offline'],
    datasets: [
      {
        data: [onlineCount, offlineCount],
        backgroundColor: ['rgba(75, 192, 192, 0.6)', 'rgba(255, 99, 132, 0.6)'],
        borderColor: ['rgba(75, 192, 192, 1)', 'rgba(255, 99, 132, 1)'],
        borderWidth: 1,
      },
    ],
  };

  const pieChartOptions = {
    responsive: true,
    plugins: {
      legend: {
        position: 'top',
      },
      title: {
        display: true,
        text: 'Device Status Overview',
      },
    },
  };

  return (
    <Container fluid className="p-3">
      <h1 className="mb-4 text-center">Network Monitor Dashboard</h1>

      {error && <Alert variant="danger">{error}</Alert>}

      <Row>
        <Col md={4}>
          {/* Pie Chart for Device Status Overview */}
          <Card className="mb-3">
            <Card.Header>Device Status Overview</Card.Header>
            <Card.Body>
              {devices.length > 0 ? (
                <div style={{ height: '200px' }}>
                  <Pie data={pieChartData} options={pieChartOptions} />
                </div>
              ) : (
                <p className="text-center">No devices to display status overview.</p>
              )}
            </Card.Body>
          </Card>

          <Card>
            <Card.Header className="d-flex justify-content-between align-items-center">
              Network Devices
              <Button variant="primary" size="sm" onClick={() => setShowAddDeviceModal(true)}>
                Add New Device
              </Button>
            </Card.Header>
            <ListGroup variant="flush" key="device-list">
              {loading ? (
                <ListGroup.Item className="text-center">
                  <Spinner animation="border" size="sm" /> Loading devices...
                </ListGroup.Item>
              ) : devices.length === 0 ? (
                <ListGroup.Item className="text-center">No devices found.</ListGroup.Item>
              ) : (
                devices.map((device) => (
                  <ListGroup.Item
                    key={device.id}
                    className="d-flex justify-content-between align-items-center"
                  >
                    <div onClick={() => handleDeviceClick(device)} style={{ flexGrow: 1, cursor: 'pointer' }}>
                      {device.name} ({device.ip}) - <span className={device.status === "online" ? "text-success" : "text-danger"}>{device.status}</span>
                    </div>
                    <div>
                      <Button
                        variant="outline-info"
                        size="sm"
                        className="me-2"
                        onClick={(e) => {
                          e.stopPropagation();
                          window.open(`http://${device.ip}`, '_blank');
                        }}
                      >
                        Login
                      </Button>
                      <Button
                        variant="outline-secondary"
                        size="sm"
                        className="me-2"
                        onClick={(e) => {
                          e.stopPropagation(); // Prevent triggering device click
                          setDeviceToEdit(device);
                          setShowEditDeviceModal(true);
                        }}
                      >
                        Edit
                      </Button>
                      <Button
                        variant="outline-danger"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation(); // Prevent triggering device click
                          setDeviceToDelete(device);
                          setShowDeleteConfirmModal(true);
                        }}
                      >
                        Delete
                      </Button>
                    </div>
                  </ListGroup.Item>
                ))
              )}
            </ListGroup>
          </Card>
        </Col>

        <Col md={8}>
          {selectedDevice ? (
            <Card>
              <Card.Header>Device Details: {selectedDevice.name} ({selectedDevice.ip})</Card.Header>
              <Card.Body>
                <p><strong>Status:</strong> <span className={selectedDevice.status === "online" ? "text-success" : "text-danger"}>{selectedDevice.status || 'N/A'}</span></p>
                {selectedDevice.sys_descr && <p><strong>Description:</strong> {selectedDevice.sys_descr}</p>}
                
                {loading && !deviceMetrics ? (
                  <div className="text-center">
                    <Spinner animation="border" size="sm" /> Loading metrics...
                  </div>
                ) : deviceMetrics ? (
                  <div>
                    <h5>Metrics:</h5>
                    <ListGroup horizontal className="mb-3">
                      {Object.entries(deviceMetrics).map(([key, value]) => (
                        <ListGroup.Item
                          key={key}
                          action
                          onClick={() => handleMetricClick(key)}
                          active={selectedMetricForChart === key}
                        >
                          <strong>{key}:</strong> {value || 'N/A'}
                        </ListGroup.Item>
                      ))}
                    </ListGroup>

                    {selectedMetricForChart && chartData ? (
                      <div style={{ width: '100%', height: '300px' }}>
                        <Line data={chartData} options={chartOptions} />
                      </div>
                    ) : (
                      <p>Click on a metric above to see its historical data.</p>
                    )}
                  </div>
                ) : (
                  <p>Select a device to view its metrics.</p>
                )}
              </Card.Body>
            </Card>
          ) : (
            <Card className="text-center p-5">
              <Card.Body>
                <Card.Title>Welcome to Network Monitor</Card.Title>
                <Card.Text>Select a device from the left panel to view its details and metrics.</Card.Text>
              </Card.Body>
            </Card>
          )}
        </Col>
      </Row>

      {/* Add Device Modal */}
      <Modal show={showAddDeviceModal} onHide={() => setShowAddDeviceModal(false)}>
        <Modal.Header closeButton>
          <Modal.Title>Add New Network Device</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form>
            <Form.Group className="mb-3" controlId="formDeviceIp">
              <Form.Label>Device IP</Form.Label>
              <Form.Control
                type="text"
                placeholder="e.g., 192.168.1.1"
                value={newDevice.ip}
                onChange={(e) => setNewDevice({ ...newDevice, ip: e.target.value })}
              />
            </Form.Group>
            <Form.Group className="mb-3" controlId="formDeviceName">
              <Form.Label>Device Name</Form.Label>
              <Form.Control
                type="text"
                placeholder="e.g., Router 1"
                value={newDevice.name}
                onChange={(e) => setNewDevice({ ...newDevice, name: e.target.value })}
              />
            </Form.Group>
            <Form.Group className="mb-3" controlId="formCommunityString">
              <Form.Label>Community String</Form.Label>
              <Form.Control
                type="text"
                placeholder="e.g., public"
                value={newDevice.community}
                onChange={(e) => setNewDevice({ ...newDevice, community: e.target.value })}
              />
            </Form.Group>
          </Form>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowAddDeviceModal(false)}>
            Close
          </Button>
          <Button variant="primary" onClick={handleAddDevice}>
            Add Device
          </Button>
        </Modal.Footer>
      </Modal>

      {/* Edit Device Modal */}
      <Modal show={showEditDeviceModal} onHide={() => setShowEditDeviceModal(false)}>
        <Modal.Header closeButton>
          <Modal.Title>Edit Network Device</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form>
            <Form.Group className="mb-3" controlId="formEditDeviceIp">
              <Form.Label>Device IP</Form.Label>
              <Form.Control
                type="text"
                value={deviceToEdit?.ip || ''}
                disabled // IP should not be editable as it's the key
              />
            </Form.Group>
            <Form.Group className="mb-3" controlId="formEditDeviceName">
              <Form.Label>Device Name</Form.Label>
              <Form.Control
                type="text"
                value={deviceToEdit?.name || ''}
                onChange={(e) => setDeviceToEdit({ ...deviceToEdit, name: e.target.value })}
              />
            </Form.Group>
            <Form.Group className="mb-3" controlId="formEditCommunityString">
              <Form.Label>Community String</Form.Label>
              <Form.Control
                type="text"
                value={deviceToEdit?.community || ''}
                onChange={(e) => setDeviceToEdit({ ...deviceToEdit, community: e.target.value })}
              />
            </Form.Group>
          </Form>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowEditDeviceModal(false)}>
            Close
          </Button>
          <Button variant="primary" onClick={handleEditDevice}>
            Save Changes
          </Button>
        </Modal.Footer>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal show={showDeleteConfirmModal} onHide={() => setShowDeleteConfirmModal(false)}>
        <Modal.Header closeButton>
          <Modal.Title>Confirm Deletion</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          Are you sure you want to delete device <strong>{deviceToDelete?.name} ({deviceToDelete?.ip})</strong>?
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowDeleteConfirmModal(false)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={handleDeleteDevice}>
            Delete
          </Button>
        </Modal.Footer>
      </Modal>
    </Container>
  );
}

export default App;
