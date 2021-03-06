import AppBar from '@material-ui/core/AppBar'
import ArcGISLayerModal from './ArcGISLayerModal'
import Button from '@material-ui/core/Button'
import DownloadModal from './DownloadModal'
import PropTypes from 'prop-types'
import React from 'react'
import Toolbar from '@material-ui/core/Toolbar'
import Tooltip from '@material-ui/core/Tooltip'
import Typography from '@material-ui/core/Typography'
import { connect } from 'react-redux'
import { withStyles } from '@material-ui/core/styles'

const styles = {
    root: {
        flexGrow: 1,
    },
    flex: {
        flexGrow: 1,
    },
    capitalize: {
        textTransform: 'capitalize'
    }
}

class GeopackageAppBar extends React.Component {
    state = {
        downloadModalOpen: false,
        ArcGISModalOpen: false,
    }
    handleArcGISModal = () => {
        const { ArcGISModalOpen } = this.state
        this.setState({ ArcGISModalOpen: !ArcGISModalOpen })
    }
    handleDownloadModal = () => {
        const { downloadModalOpen } = this.state
        this.setState({ downloadModalOpen: !downloadModalOpen })
    }
    render() {
        const { downloadModalOpen, ArcGISModalOpen } = this.state
        const { classes, title, urls } = this.props
        return (
            <div className={classes.root}>
                <AppBar position="static">
                    <Toolbar>
                        <Typography variant="title" color="inherit" className={classes.flex}>
                            {title}
                        </Typography>
                        <Button classes={{ label: classes.capitalize }} onClick={() => window.location.href = '/'} color="inherit">{"Home"}</Button>
                        <Tooltip title="Import GeoPackage, Shapefile, CSV, Raster or KML">
                            <Button classes={{ label: classes.capitalize }} onClick={() => window.location.href = urls.layerUpload} color="inherit">{"Upload Shapefile"}</Button>
                        </Tooltip>
                        {/* <Button classes={{ label: classes.capitalize }} onClick={this.handleArcGISModal} color="inherit">{"ArcGIS Publisher"}</Button> */}
                        <Button classes={{ label: classes.capitalize }} onClick={this.handleDownloadModal} color="inherit">{"Download"}</Button>
                    </Toolbar>
                </AppBar>
                <ArcGISLayerModal handleArcGISModal={this.handleArcGISModal} ArcGISModalOpen={ArcGISModalOpen} />
                <DownloadModal handleDownloadModal={this.handleDownloadModal} downloadModalOpen={downloadModalOpen} />
            </div>
        )
    }
}
const mapStateToProps = (state) => {
    return {
        urls: state.urls
    }
}
GeopackageAppBar.propTypes = {
    classes: PropTypes.object.isRequired,
    title: PropTypes.string.isRequired,
    urls: PropTypes.object.isRequired,
}
export default connect(mapStateToProps, {})(withStyles(styles)(GeopackageAppBar))