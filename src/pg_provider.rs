use pyo3::prelude::*;
use std::sync::Arc;

use crate::runtime::TOKIO_RT;

/// Wraps duroxide-pg's PostgresProvider for use from Python.
#[pyclass]
pub struct PyPostgresProvider {
    pub(crate) inner: Arc<dyn duroxide::providers::Provider>,
}

#[pymethods]
impl PyPostgresProvider {
    /// Connect to a PostgreSQL database.
    /// Uses the default "public" schema.
    #[staticmethod]
    fn connect(database_url: String) -> PyResult<Self> {
        let provider = TOKIO_RT.block_on(async {
            duroxide_pg::PostgresProvider::new(&database_url)
                .await
                .map_err(|e| {
                    pyo3::exceptions::PyRuntimeError::new_err(format!(
                        "Failed to connect to PostgreSQL: {e}"
                    ))
                })
        })?;
        Ok(Self {
            inner: Arc::new(provider),
        })
    }

    /// Connect to a PostgreSQL database with a custom schema.
    /// The schema will be created if it does not exist.
    #[staticmethod]
    fn connect_with_schema(database_url: String, schema: String) -> PyResult<Self> {
        let provider = TOKIO_RT.block_on(async {
            duroxide_pg::PostgresProvider::new_with_schema(&database_url, Some(&schema))
                .await
                .map_err(|e| {
                    pyo3::exceptions::PyRuntimeError::new_err(format!(
                        "Failed to connect to PostgreSQL: {e}"
                    ))
                })
        })?;
        Ok(Self {
            inner: Arc::new(provider),
        })
    }
}
