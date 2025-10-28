from flask import Flask, render_template, redirect, url_for, request, abort
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TextAreaField, IntegerField, BooleanField
from wtforms.validators import DataRequired, Optional
from sqlalchemy import Table, MetaData, Integer, String, Text, Boolean, Date, DateTime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'a961e74034a2bd2542e685814ddc6777fab41f0d810bf30905f4ba2d7669a651'
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://dongwkim:12345678@localhost:5432/srma'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# -------- Database Model --------
class Study(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    author = db.Column(db.String(255))
    year = db.Column(db.Integer)
    title = db.Column(db.String(1000))
    abstract = db.Column(db.Text)
    doi = db.Column(db.String(255))
    study_id = db.Column(db.String(255))
    title_abstract_screening = db.Column(db.String(10))  # yes/no/maybe
    pdf = db.Column(db.String(1000))
    included = db.Column(db.String(10))  # yes/no
    reasons = db.Column(db.Text)

# -------- Form --------
class StudyForm(FlaskForm):
    author = StringField('Author', validators=[DataRequired()])
    year = StringField('Year', validators=[DataRequired()])
    title = TextAreaField('Title', validators=[DataRequired()])
    abstract = TextAreaField('Abstract', validators=[Optional()])
    doi = StringField('DOI', validators=[Optional()])
    study_id = StringField('Study ID', validators=[Optional()])
    title_abstract_screening = SelectField('Screening', choices=[('yes','Yes'),('no','No'),('maybe','Maybe')], validators=[Optional()])
    pdf = StringField('PDF link / missing', validators=[Optional()])
    included = SelectField('Included', choices=[('yes','Yes'),('no','No')], validators=[Optional()])
    reasons = TextAreaField('Reasons', validators=[Optional()])


# -------- Dynamic form generator --------
def generate_form_from_table(table_name):
    """Reflect a table from the connected database and return a FlaskForm subclass.

    - Skips primary key columns (assumes they are auto generated)
    - Maps common SQL types to WTForms fields
    """
    metadata = MetaData()
    try:
        table = Table(table_name, metadata, autoload_with=db.engine)
    except Exception as e:
        raise RuntimeError(f"Unable to reflect table {table_name}: {e}")

    fields = {}
    for col in table.columns:
        # skip primary key columns (don't edit id fields in form)
        if col.primary_key:
            continue

        label = col.name.replace('_', ' ').title()
        validators = []
        if not col.nullable and col.default is None:
            validators.append(DataRequired())
        else:
            validators.append(Optional())

        coltype = col.type
        # Map SQLAlchemy types to WTForms fields
        if isinstance(coltype, Integer):
            field = IntegerField(label, validators=validators)
        elif isinstance(coltype, (Text,)):
            field = TextAreaField(label, validators=validators)
        elif isinstance(coltype, Boolean):
            # simple yes/no select for booleans for compatibility with existing templates
            field = SelectField(label, choices=[('','--'),('1','Yes'),('0','No')], validators=validators)
        elif isinstance(coltype, (Date, DateTime)):
            # fallback to string input for dates to avoid extra dependencies
            field = StringField(label, validators=validators)
        elif isinstance(coltype, String):
            # use textarea for very long varchars
            length = getattr(coltype, 'length', None)
            if length and length > 200:
                field = TextAreaField(label, validators=validators)
            else:
                field = StringField(label, validators=validators)
        else:
            # default fallback
            field = StringField(label, validators=validators)

        fields[col.name] = field

    # create a dynamic FlaskForm subclass
    return type(f"{table_name.capitalize()}AutoForm", (FlaskForm,), fields)


@app.route('/auto/<table_name>/add', methods=['GET', 'POST'])
def auto_add(table_name):
    """Render an auto-generated form for adding a row to `table_name`."""
    try:
        FormClass = generate_form_from_table(table_name)
    except RuntimeError as e:
        return render_template('index.html', studies=[], error=str(e)), 400

    form = FormClass()
    if form.validate_on_submit():
        # reflect table and insert values
        metadata = MetaData()
        table = Table(table_name, metadata, autoload_with=db.engine)
        values = {name: getattr(form, name).data for name in form._fields}
        try:
            db.session.execute(table.insert().values(**values))
            db.session.commit()
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            return render_template('form.html', form=form, action='Add', error=str(e)), 500

    return render_template('form.html', form=form, action=f'Add {table_name}')


@app.route('/auto/<table_name>/edit/<pk>', methods=['GET', 'POST'])
def auto_edit(table_name, pk):
    """Render an auto-generated form for editing a single-row table entry identified by primary key value `pk`.

    Assumes a single-column primary key. `pk` is treated as string and compared accordingly.
    """
    metadata = MetaData()
    try:
        table = Table(table_name, metadata, autoload_with=db.engine)
    except Exception as e:
        abort(400, f"Unable to reflect table {table_name}: {e}")

    pk_cols = [c for c in table.primary_key.columns]
    if len(pk_cols) != 1:
        abort(400, 'auto_edit currently supports tables with a single primary key column')

    pk_col = pk_cols[0]
    FormClass = generate_form_from_table(table_name)
    # load existing row
    sel = table.select().where(pk_col == pk)
    row = db.session.execute(sel).fetchone()
    if row is None:
        abort(404, 'Row not found')

    form = FormClass(data=dict(row))
    if form.validate_on_submit():
        values = {name: getattr(form, name).data for name in form._fields}
        upd = table.update().where(pk_col == pk).values(**values)
        try:
            db.session.execute(upd)
            db.session.commit()
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            return render_template('form.html', form=form, action=f'Edit {table_name}', error=str(e)), 500

    return render_template('form.html', form=form, action=f'Edit {table_name}')

# -------- Routes --------
@app.route('/')
def index():
    studies = Study.query.all()
    return render_template('index.html', studies=studies)

@app.route('/add', methods=['GET', 'POST'])
def add_study():
    form = StudyForm()
    if form.validate_on_submit():
        new_study = Study(
            author=form.author.data,
            year=form.year.data,
            title=form.title.data,
            abstract=form.abstract.data,
            doi=form.doi.data,
            study_id=form.study_id.data,
            title_abstract_screening=form.title_abstract_screening.data,
            pdf=form.pdf.data,
            included=form.included.data,
            reasons=form.reasons.data
        )
        db.session.add(new_study)
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('form.html', form=form, action='Add')

@app.route('/edit/<int:study_id>', methods=['GET', 'POST'])
def edit_study(study_id):
    study = Study.query.get_or_404(study_id)
    form = StudyForm(obj=study)
    if form.validate_on_submit():
        form.populate_obj(study)
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('form.html', form=form, action='Edit')

# -------- Run --------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        app.run(debug=True)